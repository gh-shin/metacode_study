"""EDA 캐시(Parquet)·Google Takeout 매니페스트에서 PhotoRecord를 로드해 DB에 적재한다."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from eddr.db.repository import EddrDatabase, PhotoRecord

# D18 영상 제외 — 파일 경로 기반 경로(vision_manifest·takeout·photos export 매핑)의 공통 필터.
# photos_meta 행은 ismovie 플래그로도 방어한다 (_is_indexable_photos_row).
VIDEO_EXTENSIONS = frozenset(
    {".mov", ".mp4", ".m4v", ".avi", ".mpg", ".mpeg", ".wmv", ".3gp", ".webm", ".mkv", ".mts"}
)

# EXIF DateTimeOriginal 형식(`YYYY:MM:DD HH:MM:SS`) — SQLite 날짜 함수가 못 읽으므로 ISO로 정규화.
_EXIF_DATETIME = re.compile(r"^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$")

# 모든 taken_at의 단일 기준 시간대 — KST(UTC+9). 소스별 포맷 혼재(aware UTC·naive local)를
# 이 한 표현으로 수렴시켜 SQLite datetime() 비교가 인스턴트 일관성을 갖게 한다 (D26 M1).
_KST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class SourceLoadReport:
    """소스 로드 결과 요약.

    Attributes:
        loaded: 성공적으로 upsert된 레코드 수.
        skipped: 파일 미존재 등으로 건너뛴 레코드 수.
        errors: 파싱·DB 오류로 실패한 레코드 수.
    """

    loaded: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(frozen=True)
class NormalizeTakenAtReport:
    """taken_at KST 정규화 백필 결과 요약 (D26 M1).

    Attributes:
        raw_snapshotted: taken_at_raw에 원본을 새로 복사한 행 수.
        changed_by_source: 정규화로 taken_at 값이 바뀐 행 수(소스별).
        calendar_day_changed_by_source: 달력일(앞 10자)이 바뀐 행 수(소스별).
        remaining_without_kst: 정규화 후에도 +09:00이 안 붙은 잔존 행 수(기대 0).
    """

    raw_snapshotted: int = 0
    changed_by_source: dict[str, int] = field(default_factory=dict)
    calendar_day_changed_by_source: dict[str, int] = field(default_factory=dict)
    remaining_without_kst: int = 0


def load_available_sources(
    db: EddrDatabase,
    eda_cache_dir: Path,
    takeout_manifest: Path,
    photos_export_dir: Path,
) -> SourceLoadReport:
    """사용 가능한 모든 소스를 DB에 로드하고 결과를 반환한다.

    vision_manifest.parquet → photos_meta.parquet → takeout_manifest 순으로 처리한다.
    각 파일이 존재할 때만 해당 소스를 처리한다.

    Args:
        db: 레코드를 저장할 EddrDatabase 인스턴스.
        eda_cache_dir: vision_manifest.parquet·photos_meta.parquet가 위치한 디렉터리.
        takeout_manifest: Google Takeout JSONL 매니페스트 파일 경로.
        photos_export_dir: Photos Library 내보내기 이미지가 저장된 디렉터리.

    Returns:
        로드·건너뜀·오류 건수를 담은 SourceLoadReport.
    """
    loaded = skipped = errors = 0

    vision_manifest = eda_cache_dir / "vision_manifest.parquet"
    if vision_manifest.exists():
        for record in _records_from_vision_manifest(vision_manifest, takeout_manifest.exists()):
            if record is None:
                skipped += 1
                continue
            db.upsert_photo(record)
            loaded += 1

    photos_meta = eda_cache_dir / "photos_meta.parquet"
    if photos_meta.exists():
        for record in _records_from_photos_meta(photos_meta, photos_export_dir):
            if record is None:
                skipped += 1
                continue
            db.upsert_photo(record)
            loaded += 1

    if takeout_manifest.exists():
        for line in takeout_manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = _record_from_takeout_row(json.loads(line))
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                db.record_error(None, "load_takeout", str(exc))
                errors += 1
                continue
            if record is None:
                skipped += 1
                continue
            db.upsert_photo(record)
            loaded += 1

    return SourceLoadReport(loaded=loaded, skipped=skipped, errors=errors)


def normalize_taken_at_backfill(db: EddrDatabase) -> NormalizeTakenAtReport:
    """photos.taken_at을 KST로 일괄 정규화하고 원본을 taken_at_raw에 스냅샷한다 (D26 M1).

    1) taken_at_raw가 비고 taken_at이 있는 행에 원본을 1회성으로 복사한다(재실행해도
       기존 스냅샷은 덮지 않는다).
    2) 모든 행에 ``normalize_taken_at_kst``를 적용하되 값이 실제로 바뀐 행만 UPDATE한다
       — 이미 +09:00인 값은 변환이 항등이라 재실행이 멱등하다.

    값 변환은 SQLite가 못 하는 시간대 연산이라 Python에서 행별로 수행한다.
    NULL taken_at은 건드리지 않는다.

    Args:
        db: 대상 EddrDatabase 인스턴스(백업·잠금 검사는 호출 측 책임).

    Returns:
        스냅샷·변환·달력일 변경 건수와 잔존 비-KST 행 수를 담은 리포트.
    """
    changed: dict[str, int] = {}
    day_changed: dict[str, int] = {}
    with db.connect() as conn:
        snapshotted = int(
            conn.execute(
                "UPDATE photos SET taken_at_raw = taken_at"
                " WHERE taken_at_raw IS NULL AND taken_at IS NOT NULL"
            ).rowcount
        )
        rows = conn.execute(
            "SELECT id, source, taken_at FROM photos WHERE taken_at IS NOT NULL"
        ).fetchall()
        for row in rows:
            original = row["taken_at"]
            normalized = normalize_taken_at_kst(original)
            if normalized == original:
                continue
            conn.execute(
                "UPDATE photos SET taken_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (normalized, row["id"]),
            )
            source = row["source"]
            changed[source] = changed.get(source, 0) + 1
            if (normalized or "")[:10] != (original or "")[:10]:
                day_changed[source] = day_changed.get(source, 0) + 1
        remaining = int(
            conn.execute(
                "SELECT COUNT(*) FROM photos"
                " WHERE taken_at IS NOT NULL AND taken_at NOT LIKE '%+09:00'"
            ).fetchone()[0]
        )
    return NormalizeTakenAtReport(
        raw_snapshotted=snapshotted,
        changed_by_source=changed,
        calendar_day_changed_by_source=day_changed,
        remaining_without_kst=remaining,
    )


def _records_from_vision_manifest(path: Path, has_takeout_manifest: bool):
    """vision_manifest.parquet에서 PhotoRecord 제너레이터를 반환한다.

    google_takeout 소스이고 takeout_manifest가 있으면 해당 행을 건너뛴다 (None yield).
    영상 확장자(D18)이거나 이미지 파일이 존재하지 않으면 None을 yield한다.
    """
    df = pd.read_parquet(path)
    for row in df.to_dict("records"):
        source = row.get("source")
        if source == "google_takeout" and has_takeout_manifest:
            continue
        image_path = _clean_str(row.get("local_path"))
        if not image_path or _is_video_path(image_path) or not Path(image_path).exists():
            yield None
            continue
        content_hash = _clean_str(row.get("blake3")) or _stable_hash(image_path)
        yield PhotoRecord(
            id=f"{source}:{content_hash}",
            source=str(source),
            source_uri=image_path,
            image_path=image_path,
            content_hash=content_hash,
            perceptual_hash=_clean_str(row.get("dhash")),
            taken_at=_iso_or_none(row.get("exif_date")),
            latitude=_float_or_none(row.get("gps_lat")),
            longitude=_float_or_none(row.get("gps_lng")),
            width=_int_or_none(row.get("width")),
            height=_int_or_none(row.get("height")),
            indexing_status="meta_done",
        )


def _records_from_photos_meta(path: Path, export_dir: Path):
    """photos_meta.parquet에서 Photos Library PhotoRecord 제너레이터를 반환한다.

    숨김·스크린샷·동영상·문서앨범·미선택 버스트 등 인덱싱 불가 항목은 None을 yield한다.
    """
    df = pd.read_parquet(path)
    export_map = _exported_files_by_stem(export_dir)
    for row in df.to_dict("records"):
        if not _is_indexable_photos_row(row):
            yield None
            continue
        uuid = str(row["uuid"])
        image_path = export_map.get(uuid)
        yield PhotoRecord(
            id=f"photos_library:{uuid}",
            source="photos_library",
            source_uri=uuid,
            image_path=str(image_path) if image_path else None,
            content_hash=None,
            taken_at=_iso_or_none(row.get("date")),
            latitude=_float_or_none(row.get("lat")),
            longitude=_float_or_none(row.get("lng")),
            width=_int_or_none(row.get("width")),
            height=_int_or_none(row.get("height")),
            camera_make=_clean_str(row.get("camera_make")),
            camera_model=_clean_str(row.get("camera_model")),
            indexing_status="meta_done" if image_path else "missing_image",
        )


def _record_from_takeout_row(row: dict[str, Any]) -> PhotoRecord | None:
    """Google Takeout JSONL 한 줄 파싱 결과 dict에서 PhotoRecord를 생성한다.

    Args:
        row: takeout_manifest JSONL 한 줄을 json.loads한 dict.

    Returns:
        생성된 PhotoRecord. 영상 확장자(D18)면 None.
        staged_path 파일이 없으면 indexing_status가 ``missing_image``.
    """
    image_path = str(row["staged_path"])
    if _is_video_path(image_path):
        return None
    content_hash = _clean_str(row.get("content_hash")) or _stable_hash(image_path)
    return PhotoRecord(
        id=f"google_takeout:{content_hash}",
        source="google_takeout",
        source_uri=str(row["source_uri"]),
        image_path=image_path,
        content_hash=content_hash,
        taken_at=_iso_or_none(row.get("taken_at")),
        latitude=_float_or_none(row.get("latitude")),
        longitude=_float_or_none(row.get("longitude")),
        indexing_status="meta_done" if Path(image_path).exists() else "missing_image",
    )


def _is_indexable_photos_row(row: dict[str, Any]) -> bool:
    """Photos Library 행이 인덱싱 대상인지 판별한다.

    숨김·스크린샷·동영상·문서앨범·미선택 버스트이거나 300px 미만 이미지는 False를 반환한다.
    """
    if bool(row.get("hidden")) or bool(row.get("screenshot")) or bool(row.get("ismovie")):
        return False
    if bool(row.get("in_doc_album")):
        return False
    if bool(row.get("burst")) and not bool(row.get("burst_selected")):
        return False
    width = _int_or_none(row.get("width")) or 0
    height = _int_or_none(row.get("height")) or 0
    return width >= 300 and height >= 300


def _is_video_path(path: str | Path) -> bool:
    """경로의 확장자가 영상(D18 제외 대상)이면 True를 반환한다. 대소문자를 무시한다."""
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def _exported_files_by_stem(export_dir: Path) -> dict[str, Path]:
    """내보내기 디렉터리의 파일을 stem(확장자 없는 이름) 기준으로 매핑한다.

    같은 stem이 여러 파일에 있으면 먼저 발견된 파일이 유지된다.
    영상 파일(D18)은 매핑에서 제외한다 — Live Photo의 .mov가 사진 행의
    image_path로 연결되는 것을 막는다.
    """
    if not export_dir.exists():
        return {}
    out: dict[str, Path] = {}
    for path in export_dir.rglob("*"):
        if path.is_file() and not _is_video_path(path):
            out.setdefault(path.stem, path)
    return out


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_str(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value)
    return text if text and text != "None" else None


def _iso_or_none(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return normalize_taken_at_kst(value.isoformat())
    return normalize_taken_at_kst(_normalize_exif_datetime(str(value)))


def normalize_taken_at_kst(value: str | None) -> str | None:
    """taken_at ISO 문자열을 KST(+09:00) 단일 표현으로 정규화한다 (D26 M1).

    - tzinfo가 있는 값(``+00:00``·``Z``·기타 오프셋): 인스턴트를 보존한 채 KST로
      변환한다(``astimezone``) — 마이크로초도 보존된다.
    - naive 값(오프셋 없음, local 소스): 시각을 바꾸지 않고 ``+09:00`` 라벨만 부여한다
      (벽시계 보존, ``replace(tzinfo)``).
    - 이미 ``+09:00``인 값: astimezone이 항등이라 그대로 — 재실행이 멱등하다.
    - 파싱 불가 문자열: 원문을 그대로 반환한다(방어 — EXIF 비표준 등).

    Args:
        value: ISO 8601 형식의 촬영 일시 문자열, 또는 None.

    Returns:
        KST로 정규화된 isoformat 문자열. 입력이 None이면 None, 파싱 불가면 원문.
    """
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_KST).isoformat()
    return dt.astimezone(_KST).isoformat()


def _normalize_exif_datetime(text: str) -> str | None:
    """EXIF `YYYY:MM:DD HH:MM:SS` 문자열을 ISO 8601로 정규화한다.

    EXIF 패턴이 아니면 원문을 그대로 반환하고, EXIF 패턴이지만 무효한
    일시(예: ``0000:00:00 00:00:00``)면 None을 반환한다.
    """
    if not _EXIF_DATETIME.match(text):
        return text
    try:
        return datetime.strptime(text, "%Y:%m:%d %H:%M:%S").isoformat()
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _int_or_none(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)

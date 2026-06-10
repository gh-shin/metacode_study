"""EDA 캐시(Parquet)·Google Takeout 매니페스트에서 PhotoRecord를 로드해 DB에 적재한다."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from eddr.db.repository import EddrDatabase, PhotoRecord

# D18 영상 제외 — 파일 경로 기반 경로(vision_manifest·takeout·photos export 매핑)의 공통 필터.
# photos_meta 행은 ismovie 플래그로도 방어한다 (_is_indexable_photos_row).
VIDEO_EXTENSIONS = frozenset(
    {".mov", ".mp4", ".m4v", ".avi", ".mpg", ".mpeg", ".wmv", ".3gp", ".webm", ".mkv", ".mts"}
)


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
        return value.isoformat()
    return str(value)


def _float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _int_or_none(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    return int(value)

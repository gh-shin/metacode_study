"""Takeout 폴더 walk → record 빌드 → 날짜 필터 (ADR-0005)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pillow_heif
from PIL import Image

from eddr.google_takeout.sidecar import find_sidecar, parse_sidecar

pillow_heif.register_heif_opener()

_MEDIA_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp"}


@dataclass
class MediaRecord:
    """Takeout 미디어 파일 한 장에 대한 정규화된 레코드.

    Attributes:
        path: 파일시스템 절대 경로.
        source_uri: extracted_root 기준 상대 경로 문자열(manifest 추적용).
        taken_at: 촬영 시각(사이드카 → EXIF → 파일명 순 폴백, 없으면 None).
        latitude: 위도(geoData/geoDataExif, 0.0 쌍은 None으로 처리).
        longitude: 경도(위와 동일).
        description: Takeout 사이드카의 설명 텍스트.
        people: 태그된 인물 이름 목록.
        original_filename: 원본 파일명(경로 없이).
    """

    path: Path
    source_uri: str
    taken_at: datetime | None
    latitude: float | None
    longitude: float | None
    description: str
    people: list[str]
    original_filename: str


def in_date_range(d: date, lo: date, hi: date) -> bool:
    """[lo, hi) 반열린 구간."""
    return lo <= d < hi


def _exif_taken_at(path: Path) -> datetime | None:
    try:
        exif = Image.open(path).getexif()
        raw = exif.get(36867) or exif.get(306)  # DateTimeOriginal / DateTime
        if raw:
            return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S").replace(tzinfo=UTC)
    except Exception:
        return None
    return None


_FILENAME_DT_RE = re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})(?!\d)")
_FB_IMG_RE = re.compile(r"FB_IMG_(\d{13})(?!\d)")


def _filename_taken_at(name: str) -> datetime | None:
    """파일명에 박힌 촬영시각(최후 폴백; 사이드카·EXIF 모두 실패 시만)."""
    m = _FB_IMG_RE.search(name)
    if m:
        try:
            return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=UTC)
        except (ValueError, OSError):
            return None
    m = _FILENAME_DT_RE.search(name)
    if m:
        y, mo, d, h, mi, s = map(int, m.groups())
        if 1990 <= y <= 2035:
            try:
                return datetime(y, mo, d, h, mi, s, tzinfo=UTC)
            except ValueError:
                return None
    return None


def build_records(root: Path) -> list[MediaRecord]:
    """root 아래 미디어 파일 전체를 재귀 탐색해 MediaRecord 목록을 반환한다.

    사이드카 파싱 → EXIF → 파일명 순으로 촬영시각을 폴백하며, 사이드카 파싱
    오류는 경고만 출력하고 건너뛴다.

    Args:
        root: 탐색 루트 디렉터리(Takeout extracted/).

    Returns:
        발견된 미디어 파일별 MediaRecord 목록(정렬 순).
    """
    records: list[MediaRecord] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _MEDIA_EXT:
            continue
        sidecar = find_sidecar(path)
        meta = None
        if sidecar:
            try:
                meta = parse_sidecar(sidecar)
            except (json.JSONDecodeError, OSError) as e:
                print(f"warn: 사이드카 파싱 실패, 건너뜀: {sidecar} ({e})")
        taken_at = meta.taken_at if (meta and meta.taken_at) else _exif_taken_at(path)
        if taken_at is None:
            taken_at = _filename_taken_at(path.name)
        records.append(
            MediaRecord(
                path=path,
                source_uri=str(path.relative_to(root)),
                taken_at=taken_at,
                latitude=meta.latitude if meta else None,
                longitude=meta.longitude if meta else None,
                description=meta.description if meta else "",
                people=meta.people if meta else [],
                original_filename=path.name,
            )
        )
    return records


def filter_by_date(records: list[MediaRecord], lo: date, hi: date) -> list[MediaRecord]:
    """taken_at 가 [lo, hi) 범위인 레코드만 반환한다.

    Args:
        records: 필터 대상 MediaRecord 목록.
        lo: 날짜 하한(포함).
        hi: 날짜 상한(제외).

    Returns:
        조건을 만족하는 MediaRecord 목록(taken_at이 None인 레코드는 제외).
    """
    return [r for r in records if r.taken_at and in_date_range(r.taken_at.date(), lo, hi)]

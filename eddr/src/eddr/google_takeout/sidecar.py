"""Takeout JSON 사이드카 탐색(절단 내성) + 파싱 (ADR-0005)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class SidecarMeta:
    """Takeout JSON 사이드카에서 추출한 메타데이터.

    Attributes:
        taken_at: photoTakenTime 타임스탬프 기반 촬영 시각(없으면 None).
        latitude: geoData/geoDataExif 위도(0.0 쌍은 None으로 처리).
        longitude: geoData/geoDataExif 경도(위와 동일).
        description: 사이드카의 description 텍스트.
        people: 태그된 인물 이름 목록.
    """

    taken_at: datetime | None
    latitude: float | None
    longitude: float | None
    description: str
    people: list[str]


_SUFFIXES = (".supplemental-metadata.json", ".json")
_EDITED_MARKERS = ("-edited", "-수정됨", "수정됨")


def _media_prefix(json_name: str) -> str:
    """사이드카 파일명에서 media 파일명 부분을 복원(절단 포함)."""
    stem = json_name
    for marker in _SUFFIXES:
        if stem.endswith(marker):
            stem = stem[: -len(marker)]
            break
    # ".supplemental..."가 절단된 잔여물 제거
    if ".supplemental" in stem:
        stem = stem[: stem.index(".supplemental")]
    return stem


def find_sidecar(media_path: Path) -> Path | None:
    """미디어 파일에 대응하는 Takeout JSON 사이드카 경로를 반환한다.

    탐색 우선순위:
    1. 정확 일치 (`<name>.supplemental-metadata.json`, `<name>.json`)
    2. 편집본(-edited / 수정됨) → 원본 사이드카
    3. 절단 내성: 디렉터리 내 `.json` 파일 중 media_prefix가 파일명 접두사인
       것 중 최장 일치

    Args:
        media_path: 사이드카를 찾을 미디어 파일 경로.

    Returns:
        사이드카 Path, 없으면 None.
    """
    d, name = media_path.parent, media_path.name
    # 1) 정확 일치
    for suffix in _SUFFIXES:
        cand = d / (name + suffix)
        if cand.exists():
            return cand
    # 2) 편집본(-edited / 수정됨) → 원본 사이드카
    for marker in _EDITED_MARKERS:
        if marker in name:
            base = name.replace(marker, "")
            for suffix in _SUFFIXES:
                cand = d / (base + suffix)
                if cand.exists():
                    return cand
            name = base
            break
    # 3) 절단 내성: media_prefix가 name의 접두사인 것 중 최장
    best, best_len = None, 0
    for j in d.glob("*.json"):
        prefix = _media_prefix(j.name)
        if prefix and name.startswith(prefix) and len(prefix) > best_len:
            best, best_len = j, len(prefix)
    return best


def parse_sidecar(path: Path) -> SidecarMeta:
    """사이드카 JSON을 파싱해 SidecarMeta를 반환한다.

    Raises:
        FileNotFoundError: path가 없을 때.
        json.JSONDecodeError: JSON이 유효하지 않을 때.
    (배치 호출자 build_records가 이를 잡아 해당 파일을 건너뛴다.)
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    ts = data.get("photoTakenTime", {}).get("timestamp")
    taken_at = datetime.fromtimestamp(int(ts), tz=UTC) if ts else None
    lat = lon = None
    for key in ("geoData", "geoDataExif"):
        geo = data.get(key) or {}
        if geo.get("latitude") or geo.get("longitude"):  # 0.0/0.0 → 무시
            lat, lon = geo.get("latitude"), geo.get("longitude")
            break
    people = [p["name"] for p in data.get("people", []) if p.get("name")]
    return SidecarMeta(
        taken_at=taken_at,
        latitude=lat,
        longitude=lon,
        description=data.get("description", "") or "",
        people=people,
    )

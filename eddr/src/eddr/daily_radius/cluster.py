"""GPS 좌표 격자 밀도 클러스터링 — Daily Radius 후보 산출 (D15).

EDA 01과 같은 격자 카운트 방식(0.01° ≈ 1.1km)으로 밀도 피크를 찾고,
피크 주변 셀을 병합해 중심·반경·사진수 후보를 만든다. 후보는 어디까지나
제안이며 확정·라벨링은 setup wizard에서 사용자가 한다.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class AreaCandidate:
    """Daily Radius 후보 영역.

    Attributes:
        center_lat: 가중 중심 위도.
        center_lng: 가중 중심 경도.
        radius_km: 제안 반경(km) — wizard에서 편집 가능.
        photo_count: 병합된 셀의 사진 수 합.
        place: 표시용 대표 지명 (geocode 결과, 없으면 None).
    """

    center_lat: float
    center_lng: float
    radius_km: float
    photo_count: int
    place: str | None = None


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 사이의 대권 거리(km)를 반환한다."""
    radius_earth_km = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius_earth_km * math.asin(math.sqrt(a))


def propose_daily_radius(
    coords: list[tuple[float, float]],
    top_n: int = 8,
    cell_deg: float = 0.01,
    merge_radius_km: float = 5.0,
    min_count: int = 30,
) -> list[AreaCandidate]:
    """좌표 밀도 피크에서 Daily Radius 후보를 만든다.

    격자 카운트 후 최대 셀부터 greedy로 주변 merge_radius_km 내 셀을 병합해
    가중 중심·제안 반경을 계산한다. 병합 합계가 min_count 미만인 피크는
    버리고 계속 탐색한다 — 피크 셀 크기와 병합 총량은 단조 관계가 아니라
    이른 중단이 유효 후보를 놓칠 수 있다. 같은 이유로 결과는 마지막에
    병합 총량 내림차순으로 정렬한다.

    Args:
        coords: (lat, lng) 좌표 리스트.
        top_n: 반환할 최대 후보 수.
        cell_deg: 격자 한 변(도). 기본 0.01° ≈ 1.1km.
        merge_radius_km: 피크 주변 셀 병합 반경(km).
        min_count: 후보로 인정할 최소 사진 수.

    Returns:
        사진 수 내림차순 AreaCandidate 리스트.
    """
    cell_counts = Counter((round(lat / cell_deg), round(lng / cell_deg)) for lat, lng in coords)
    cell_km = cell_deg * 111.0
    candidates: list[AreaCandidate] = []
    while cell_counts and len(candidates) < top_n:
        peak_cell, _ = max(cell_counts.items(), key=lambda item: item[1])
        peak_lat, peak_lng = peak_cell[0] * cell_deg, peak_cell[1] * cell_deg
        merged = [
            (cell, count)
            for cell, count in cell_counts.items()
            if haversine_km(peak_lat, peak_lng, cell[0] * cell_deg, cell[1] * cell_deg)
            <= merge_radius_km
        ]
        total = sum(count for _, count in merged)
        if total < min_count:
            for cell, _ in merged:
                del cell_counts[cell]
            continue
        center_lat = sum(cell[0] * cell_deg * count for cell, count in merged) / total
        center_lng = sum(cell[1] * cell_deg * count for cell, count in merged) / total
        spread_km = max(
            haversine_km(center_lat, center_lng, cell[0] * cell_deg, cell[1] * cell_deg)
            for cell, _ in merged
        )
        radius_km = max(1.0, round(spread_km + cell_km / 2, 1))
        candidates.append(
            AreaCandidate(
                center_lat=round(center_lat, 5),
                center_lng=round(center_lng, 5),
                radius_km=radius_km,
                photo_count=total,
            )
        )
        for cell, _ in merged:
            del cell_counts[cell]
    candidates.sort(key=lambda candidate: -candidate.photo_count)
    return candidates

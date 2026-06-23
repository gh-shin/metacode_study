"""GPS·시간 기반 trip 세그멘테이션 — Daily Radius 밖 24h+ 연속 체류 (D11·D14).

일상 영역(다중) 안이면 in, 밖이면 out으로 보고 out의 연속 run을 trip 후보로
만든다. run은 in 사진 등장(복귀) 또는 out 사진 간 큰 시간 공백에서 끊기며,
체류 스팬이 min_duration_hours 이상인 run만 trip이 된다. 국경을 넘어도 복귀
전이면 1개 run이다 — 다국가 1 trip은 여기서 자연히 보장된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from eddr.daily_radius.cluster import haversine_km


@dataclass(frozen=True)
class PhotoPoint:
    """세그멘테이션 입력 한 점 — GPS와 촬영 시각이 있는 사진.

    Attributes:
        photo_id: photos.id.
        taken_at: 촬영 시각. 호출자가 tz를 통일(naive)해 넘긴다.
        latitude: 위도.
        longitude: 경도.
    """

    photo_id: str
    taken_at: datetime
    latitude: float
    longitude: float


@dataclass(frozen=True)
class TripSegment:
    """일상 반경 밖 연속 체류 구간 — trips 행의 원천.

    Attributes:
        start_at: 첫 사진 촬영 시각.
        end_at: 마지막 사진 촬영 시각.
        photo_ids: 구간에 속한 GPS 사진 id (시간순).
        center_lat: 사진 좌표 평균 위도.
        center_lng: 사진 좌표 평균 경도.
    """

    start_at: datetime
    end_at: datetime
    photo_ids: list[str]
    center_lat: float
    center_lng: float


def segment_trips(
    points: list[PhotoPoint],
    areas: list[tuple[float, float, float]],
    min_duration_hours: float = 24.0,
    max_gap_hours: float = 72.0,
) -> list[TripSegment]:
    """일상 반경 밖 사진들을 연속 체류 구간으로 묶어 trip 후보를 만든다.

    Args:
        points: GPS·시간 보유 사진들. 정렬은 함수가 보장한다.
        areas: 일상 영역 (center_lat, center_lng, radius_km) 목록.
            비어 있으면 모든 사진을 out으로 본다.
        min_duration_hours: trip으로 인정할 최소 체류 스팬(첫~끝 사진).
            기본 24h (D14 "24시간 이상").
        max_gap_hours: 복귀 사진이 없어도 run을 끊는 out 사진 간 최대 공백.
            주 신호는 복귀(in 사진)이고 이건 안전장치 — 여행 중 1~2일
            무사진은 견디고 주 단위 공백은 분리하도록 기본 72h.
            (24h는 "여행 중 하루 무촬영"을 가짜 분리 — 민감도는 D14 심화에서.)

    Returns:
        시간순 TripSegment 리스트.
    """
    ordered = sorted(points, key=lambda point: point.taken_at)
    runs: list[list[PhotoPoint]] = []
    current: list[PhotoPoint] = []
    for point in ordered:
        inside = any(
            haversine_km(point.latitude, point.longitude, lat, lng) <= radius_km
            for lat, lng, radius_km in areas
        )
        if inside:
            if current:
                runs.append(current)
                current = []
            continue
        if current and _hours_between(current[-1].taken_at, point.taken_at) > max_gap_hours:
            runs.append(current)
            current = []
        current.append(point)
    if current:
        runs.append(current)

    segments: list[TripSegment] = []
    for run in runs:
        if _hours_between(run[0].taken_at, run[-1].taken_at) < min_duration_hours:
            continue
        segments.append(
            TripSegment(
                start_at=run[0].taken_at,
                end_at=run[-1].taken_at,
                photo_ids=[point.photo_id for point in run],
                center_lat=round(sum(point.latitude for point in run) / len(run), 5),
                center_lng=round(sum(point.longitude for point in run) / len(run), 5),
            )
        )
    return segments


def _hours_between(earlier: datetime, later: datetime) -> float:
    return (later - earlier).total_seconds() / 3600.0

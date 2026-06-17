"""trip 재계산 파이프라인 — 세그멘테이션 결과를 trips·trip_countries·photos에 반영 (PLAN §5 [8]).

전체 재계산(리셋 후 다시 배정)이라 멱등하다. 세그먼트 경계는 naive UTC
``YYYY-MM-DD HH:MM:SS``(초 절삭)로 기록하며, 사진 측 비교도 SQLite datetime()
정규화가 같은 절삭을 적용해 첫/끝 사진이 경계에 포함된다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from eddr.db.repository import EddrDatabase, PhotoRecord
from eddr.geocode.pipeline import quantize
from eddr.trips.cluster import PhotoPoint, TripSegment, segment_trips

# 거주국 — name 규칙의 국내/해외 판정과 trip_countries의 거주국 제외 기준.
# 표기는 Nominatim accept-language=ko 실측값, 코드는 ISO 3166-1 alpha-2.
HOME_COUNTRY = "대한민국"
HOME_COUNTRY_CODE = "KR"


@dataclass(frozen=True)
class TripRecomputeReport:
    """trip 재계산 결과 요약.

    Attributes:
        trips_created: 생성된 trip 수.
        photos_assigned: trip_id가 배정된 사진 수 (기간 내 no-GPS 포함, 영상 제외).
    """

    trips_created: int = 0
    photos_assigned: int = 0


def recompute_trips(
    db: EddrDatabase,
    min_duration_hours: float = 24.0,
    max_gap_hours: float = 72.0,
) -> TripRecomputeReport:
    """trip을 전체 재계산한다 — 기존 배정을 지우고 세그먼트부터 다시 만든다.

    GPS·시간 보유 사진(영상 제외)으로 세그먼트를 만들고, trip마다 이름·기간·
    중심을 기록한 뒤 기간 내 사진(no-GPS 포함)에 trip_id를 배정한다.
    방문 국가는 사진 좌표의 양자화 셀로 geocode_cache의 ISO 코드를 모은다.

    Args:
        db: 대상 데이터베이스.
        min_duration_hours: trip 인정 최소 체류 스팬 (D14 기본 24h).
        max_gap_hours: 복귀 사진 없이 run을 끊는 최대 사진 공백 (기본 72h).

    Returns:
        생성 trip·배정 사진 수를 담은 TripRecomputeReport.
    """
    records = db.photos_for_trip_clustering()
    by_id = {record.id: record for record in records}
    points = []
    for record in records:
        taken_at = _parse_taken_at(record.taken_at)
        if taken_at is None:
            continue
        points.append(
            PhotoPoint(
                photo_id=record.id,
                taken_at=taken_at,
                latitude=record.latitude,
                longitude=record.longitude,
            )
        )
    areas = [
        (area.center_lat, area.center_lng, area.radius_km) for area in db.list_daily_radius_areas()
    ]
    segments = segment_trips(
        points, areas, min_duration_hours=min_duration_hours, max_gap_hours=max_gap_hours
    )

    db.reset_trip_assignments()
    photos_assigned = 0
    seq_by_day: Counter[str] = Counter()
    for segment in segments:
        day = f"{segment.start_at:%Y%m%d}"
        seq_by_day[day] += 1
        trip_id = f"trip_{day}_{seq_by_day[day]:02d}"
        segment_records = [by_id[photo_id] for photo_id in segment.photo_ids]
        start_at, end_at = _fmt(segment.start_at), _fmt(segment.end_at)
        db.insert_trip(
            trip_id,
            _make_trip_name(segment_records, segment),
            start_at,
            end_at,
            segment.center_lat,
            segment.center_lng,
        )
        photos_assigned += db.assign_trip_by_timerange(trip_id, start_at, end_at)
        codes = _collect_country_codes(db, segment_records)
        if codes:
            db.insert_trip_countries(trip_id, codes)
    db.finalize_trip_photo_counts()
    return TripRecomputeReport(trips_created=len(segments), photos_assigned=photos_assigned)


def _parse_taken_at(value: str | None) -> datetime | None:
    """ISO 8601 문자열을 naive UTC datetime으로 정규화한다.

    aware(+00:00)는 UTC 변환 후 tzinfo를 떼고, naive(local 소스)는 UTC로
    간주한다 — tz 미상 EXIF 시각의 보수적 처리(24h 단위 클러스터링엔 충분).
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _fmt(when: datetime) -> str:
    return when.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _make_trip_name(records: list[PhotoRecord], segment: TripSegment) -> str:
    """trip 이름을 만든다 — "이탈리아 여행 2018-04" (PLAN §4.1).

    해외 사진이 있으면 최빈 외국 국가명, 국내뿐이면 최빈 city, 지명이 전혀
    없으면(바다 등) 지명 없이 시작 연월만 쓴다.
    """
    foreign = [r.country for r in records if r.country and r.country != HOME_COUNTRY]
    if foreign:
        place = Counter(foreign).most_common(1)[0][0]
    else:
        cities = [r.city for r in records if r.city]
        place = Counter(cities).most_common(1)[0][0] if cities else None
    month = f"{segment.start_at:%Y-%m}"
    return f"{place} 여행 {month}" if place else f"여행 {month}"


def _collect_country_codes(db: EddrDatabase, records: list[PhotoRecord]) -> list[str]:
    """사진 좌표의 양자화 셀에서 방문 국가 ISO 코드 집합을 모은다 (정렬, 결정적).

    해외 trip이면 거주국 코드를 제외한다 — 출국·귀국일 공항 사진이 trip에
    묶여도 거주국은 방문국이 아니다(CONTEXT.md: 인천→로마→뮌헨→인천 =
    trip-country 2개). 국내 trip은 거주국 코드가 그대로 남는다.
    """
    cells = {(quantize(r.latitude), quantize(r.longitude)) for r in records}
    codes = set()
    for cell in cells:
        cached = db.get_geocode_cache(*cell)
        if cached and cached.country_code:
            codes.add(cached.country_code)
    if codes - {HOME_COUNTRY_CODE}:
        codes.discard(HOME_COUNTRY_CODE)
    return sorted(codes)

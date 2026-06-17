from datetime import datetime, timedelta

from eddr.trips.cluster import PhotoPoint, segment_trips

# 일상 영역: 서울 강남 일대 5km (wizard 확정 형식과 동일한 (lat, lng, radius_km)).
HOME = (37.506, 127.040, 5.0)
# 영역 밖 좌표들.
GANGWON = (37.795, 128.918)  # 평창 — 집에서 약 170km
ROME = (41.902, 12.496)
SEOUL_HOME = (37.507, 127.041)  # HOME 중심 인근 (반경 내)


def _dt(day: int, hour: int = 12) -> datetime:
    return datetime(2019, 6, day, hour, 0, 0)


def _point(photo_id: str, when: datetime, lat: float, lng: float) -> PhotoPoint:
    return PhotoPoint(photo_id=photo_id, taken_at=when, latitude=lat, longitude=lng)


def test_all_photos_inside_daily_radius_yield_no_trips():
    points = [_point(f"p{i}", _dt(1 + i), *SEOUL_HOME) for i in range(5)]

    assert segment_trips(points, [HOME]) == []


def test_continuous_stay_outside_radius_becomes_one_trip():
    points = [
        _point("p1", _dt(1, 10), *GANGWON),
        _point("p2", _dt(2, 9), *GANGWON),
        _point("p3", _dt(3, 18), *GANGWON),
    ]

    trips = segment_trips(points, [HOME])

    assert len(trips) == 1
    trip = trips[0]
    assert trip.start_at == _dt(1, 10)
    assert trip.end_at == _dt(3, 18)
    assert trip.photo_ids == ["p1", "p2", "p3"]
    assert trip.center_lat == 37.795
    assert trip.center_lng == 128.918


def test_return_to_daily_radius_splits_trips():
    points = [
        _point("out1a", _dt(1, 10), *GANGWON),
        _point("out1b", _dt(2, 18), *GANGWON),
        _point("home", _dt(3, 12), *SEOUL_HOME),  # 복귀
        _point("out2a", _dt(5, 10), *ROME),
        _point("out2b", _dt(7, 18), *ROME),
    ]

    trips = segment_trips(points, [HOME])

    assert [t.photo_ids for t in trips] == [["out1a", "out1b"], ["out2a", "out2b"]]


def test_day_outing_under_min_duration_is_not_a_trip():
    points = [
        _point("p1", _dt(1, 9), *GANGWON),
        _point("p2", _dt(1, 20), *GANGWON),  # 같은 날 11시간 — 24h 미만
    ]

    assert segment_trips(points, [HOME]) == []


def test_long_photo_gap_splits_trips_even_without_return_photo():
    points = [
        _point("p1", _dt(1, 10), *GANGWON),
        _point("p2", _dt(2, 12), *GANGWON),
        # 사진 공백 74h(기본 72h 초과) — 복귀 사진은 없지만 같은 trip으로 보지 않는다.
        _point("p3", _dt(5, 14), *GANGWON),
        _point("p4", _dt(6, 16), *GANGWON),
    ]

    trips = segment_trips(points, [HOME])

    assert [t.photo_ids for t in trips] == [["p1", "p2"], ["p3", "p4"]]


def test_multi_country_without_return_stays_one_trip():
    # 인천 → 로마 → (이동) → 평창급 거리라도 복귀 전이면 1 trip (D14).
    points = [
        _point("p1", _dt(1, 10), *ROME),
        _point("p2", _dt(2, 10), 48.137, 11.575),  # 뮌헨
        _point("p3", _dt(3, 10), *ROME),
    ]

    trips = segment_trips(points, [HOME])

    assert len(trips) == 1
    assert trips[0].photo_ids == ["p1", "p2", "p3"]


def test_unsorted_input_is_sorted_by_time():
    points = [
        _point("late", _dt(3, 18), *GANGWON),
        _point("early", _dt(1, 10), *GANGWON),
        _point("mid", _dt(2, 9) + timedelta(minutes=30), *GANGWON),
    ]

    trips = segment_trips(points, [HOME])

    assert trips[0].photo_ids == ["early", "mid", "late"]


def test_no_daily_radius_areas_treats_everything_as_one_run():
    # 영역 미설정이어도 갭·기간 규칙만으로 동작해야 한다 (방어).
    points = [
        _point("p1", _dt(1, 10), *SEOUL_HOME),
        _point("p2", _dt(2, 18), *SEOUL_HOME),
    ]

    trips = segment_trips(points, [])

    assert len(trips) == 1

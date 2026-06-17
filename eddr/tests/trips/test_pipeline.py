from pathlib import Path

from eddr.db.repository import EddrDatabase, PhotoRecord
from eddr.trips.pipeline import recompute_trips

HOME = ("집", 37.506, 127.040, 5.0)
GANGNEUNG = (37.795, 128.918)
ROME = (41.902, 12.496)


def _make_db(tmp_path: Path) -> EddrDatabase:
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.replace_daily_radius_areas([HOME])
    return db


def _add_photo(
    db: EddrDatabase,
    photo_id: str,
    taken_at: str | None,
    lat: float | None = None,
    lng: float | None = None,
    status: str = "caption_done",
    country: str | None = None,
    city: str | None = None,
) -> None:
    db.upsert_photo(
        PhotoRecord(
            id=photo_id,
            source="photos_library",
            source_uri=photo_id,
            taken_at=taken_at,
            latitude=lat,
            longitude=lng,
            indexing_status=status,
        )
    )
    if country or city:
        db.update_photo_geo(photo_id, country, city, None)


def _add_gangneung_weekend(db: EddrDatabase) -> None:
    """강릉 2박 3일 — 일상 사진 사이에 끼운 trip 시나리오."""
    _add_photo(db, "pl:home1", "2019-05-30T09:00:00+00:00", 37.507, 127.041)
    for i, hour in enumerate((10, 18)):
        _add_photo(
            db,
            f"pl:gn1_{i}",
            f"2019-06-01T{hour:02d}:00:00+00:00",
            *GANGNEUNG,
            country="대한민국",
            city="강릉시",
        )
    _add_photo(
        db, "pl:gn2", "2019-06-03T18:00:00+00:00", *GANGNEUNG, country="대한민국", city="강릉시"
    )
    _add_photo(db, "pl:home2", "2019-06-04T09:00:00+00:00", 37.507, 127.041)
    db.upsert_geocode_cache(37795, 128918, "대한민국", "강릉시", None, "KR")


def test_recompute_creates_trip_with_name_countries_and_assignments(tmp_path: Path):
    db = _make_db(tmp_path)
    _add_gangneung_weekend(db)
    # 기간 내 no-GPS 사진과 영상 — no-GPS는 배정되고 영상은 빠진다.
    _add_photo(db, "pl:nogps", "2019-06-02T12:00:00+00:00")
    _add_photo(db, "pl:video", "2019-06-02T13:00:00+00:00", *GANGNEUNG, status="skipped_video")

    report = recompute_trips(db)

    assert report.trips_created == 1
    assert report.photos_assigned == 4  # 강릉 3 + no-GPS 1
    with db.connect() as conn:
        trip = conn.execute("SELECT * FROM trips").fetchone()
        codes = [r["country_code"] for r in conn.execute("SELECT country_code FROM trip_countries")]
    assert trip["id"] == "trip_20190601_01"
    assert trip["name"] == "강릉시 여행 2019-06"
    assert trip["start_at"] == "2019-06-01 10:00:00"
    assert trip["end_at"] == "2019-06-03 18:00:00"
    assert trip["photo_count"] == 4
    assert codes == ["KR"]
    assert db.get_photo("pl:gn2").trip_id == "trip_20190601_01"
    assert db.get_photo("pl:gn2").indexing_status == "trip_assigned"
    assert db.get_photo("pl:nogps").trip_id == "trip_20190601_01"
    assert db.get_photo("pl:video").trip_id is None
    assert db.get_photo("pl:home1").trip_id is None


def test_recompute_is_idempotent(tmp_path: Path):
    db = _make_db(tmp_path)
    _add_gangneung_weekend(db)

    first = recompute_trips(db)
    second = recompute_trips(db)

    assert first == second
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 1
    assert db.get_photo("pl:gn2").indexing_status == "trip_assigned"


def test_trip_name_prefers_foreign_country_over_city(tmp_path: Path):
    db = _make_db(tmp_path)
    # 출국일 인천공항 사진 — 같은 trip에 묶이지만 거주국은 방문국이 아니다
    # (CONTEXT.md: "인천 → 로마 → 뮌헨 → 인천 = 1 trip, trip-country 2개").
    _add_photo(db, "pl:icn", "2018-04-05T01:00:00+00:00", 37.46, 126.44, country="대한민국")
    db.upsert_geocode_cache(37460, 126440, "대한민국", "인천광역시", None, "KR")
    for day in (5, 6, 7):
        _add_photo(
            db,
            f"pl:rome{day}",
            f"2018-04-{day:02d}T10:00:00+00:00",
            *ROME,
            country="이탈리아",
            city="로마",
        )
    db.upsert_geocode_cache(41902, 12496, "이탈리아", "로마", None, "IT")

    recompute_trips(db)

    with db.connect() as conn:
        trip = conn.execute("SELECT * FROM trips").fetchone()
        codes = [r["country_code"] for r in conn.execute("SELECT country_code FROM trip_countries")]
    assert trip["name"] == "이탈리아 여행 2018-04"
    assert codes == ["IT"]


def test_trip_name_falls_back_without_geocode(tmp_path: Path):
    db = _make_db(tmp_path)
    for day in (5, 6, 7):
        _add_photo(db, f"pl:sea{day}", f"2018-04-{day:02d}T10:00:00+00:00", 0.0, -160.0)

    recompute_trips(db)

    with db.connect() as conn:
        trip = conn.execute("SELECT * FROM trips").fetchone()
        country_rows = conn.execute("SELECT * FROM trip_countries").fetchall()
    assert trip["name"] == "여행 2018-04"
    assert country_rows == []

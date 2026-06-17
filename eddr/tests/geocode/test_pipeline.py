from pathlib import Path

from eddr.db.repository import EddrDatabase, GeocodeCacheEntry, PhotoRecord
from eddr.geocode.nominatim import GeocodeError, GeocodeResult
from eddr.geocode.pipeline import backfill_country_codes, geocode_photos, quantize


class FakeClient:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result or GeocodeResult(country="대한민국", city="서울", district="강남구")
        self.error = error
        self.calls: list[tuple[float, float]] = []

    def reverse(self, lat: float, lng: float) -> GeocodeResult:
        self.calls.append((lat, lng))
        if self.error is not None:
            raise self.error
        return self.result


def _make_db(tmp_path: Path) -> EddrDatabase:
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    return db


def _gps_photo(photo_id: str, lat: float, lng: float) -> PhotoRecord:
    return PhotoRecord(
        id=photo_id,
        source="photos_library",
        source_uri=photo_id,
        latitude=lat,
        longitude=lng,
    )


def test_quantize_millidegrees():
    # .0005 정확 경계는 float 표현상 보증하지 않는다 — 경계 밖 값만 고정.
    assert quantize(37.5286) == 37529
    assert quantize(37.5284) == 37528
    assert quantize(-0.0004) == 0
    assert quantize(127.0) == 127000


def test_geocode_updates_photo_fields(tmp_path: Path):
    db = _make_db(tmp_path)
    db.upsert_photo(_gps_photo("photos_library:u1", 37.5285, 127.0552))
    client = FakeClient()

    report = geocode_photos(db, client)

    assert report.photos_updated == 1
    assert report.cells_fetched == 1
    row = db.get_photo("photos_library:u1")
    assert (row.country, row.city, row.district) == ("대한민국", "서울", "강남구")


def test_geocode_requests_cell_center_not_raw_coords(tmp_path: Path):
    db = _make_db(tmp_path)
    db.upsert_photo(_gps_photo("photos_library:u1", 37.52851, 127.05549))
    client = FakeClient()

    geocode_photos(db, client)

    assert client.calls == [(37.529, 127.055)]


def test_geocode_same_cell_hits_cache_once(tmp_path: Path):
    db = _make_db(tmp_path)
    db.upsert_photo(_gps_photo("photos_library:u1", 37.52851, 127.05524))
    db.upsert_photo(_gps_photo("photos_library:u2", 37.52853, 127.05526))
    client = FakeClient()

    report = geocode_photos(db, client)

    assert len(client.calls) == 1
    assert report.photos_updated == 2
    assert report.cache_hits == 1
    assert db.get_photo("photos_library:u2").city == "서울"


def test_geocode_skips_photos_without_gps_or_already_done(tmp_path: Path):
    db = _make_db(tmp_path)
    db.upsert_photo(PhotoRecord(id="local:nogps", source="local", source_uri="x"))
    db.upsert_photo(_gps_photo("photos_library:done", 37.5, 127.0))
    db.update_photo_geo("photos_library:done", "대한민국", "서울", None)
    client = FakeClient()

    report = geocode_photos(db, client)

    assert report.photos_updated == 0
    assert client.calls == []


def test_geocode_negative_result_is_cached(tmp_path: Path):
    db = _make_db(tmp_path)
    db.upsert_photo(_gps_photo("photos_library:sea1", 0.0, -160.0))
    db.upsert_photo(_gps_photo("photos_library:sea2", 0.0001, -160.0001))
    client = FakeClient(result=GeocodeResult())

    report = geocode_photos(db, client)

    assert len(client.calls) == 1
    assert report.photos_updated == 2
    assert db.get_photo("photos_library:sea1").country is None


def test_geocode_records_error_and_continues(tmp_path: Path):
    db = _make_db(tmp_path)
    db.upsert_photo(_gps_photo("photos_library:u1", 37.5, 127.0))
    client = FakeClient(error=GeocodeError("HTTP 500"))

    report = geocode_photos(db, client)

    assert report.errors == 1
    assert report.photos_updated == 0
    with db.connect() as conn:
        row = conn.execute("SELECT stage FROM index_errors").fetchone()
    assert row["stage"] == "geocode"


def test_geocode_aborts_after_consecutive_errors(tmp_path: Path):
    db = _make_db(tmp_path)
    for i in range(10):
        db.upsert_photo(_gps_photo(f"photos_library:u{i}", 10.0 + i, 100.0 + i))
    client = FakeClient(error=GeocodeError("HTTP 500"))

    report = geocode_photos(db, client, max_consecutive_errors=3)

    assert report.aborted is True
    assert report.errors == 3
    assert len(client.calls) == 3


def test_geocode_respects_limit(tmp_path: Path):
    db = _make_db(tmp_path)
    for i in range(3):
        db.upsert_photo(_gps_photo(f"photos_library:u{i}", 10.0 + i, 100.0 + i))
    client = FakeClient()

    report = geocode_photos(db, client, limit=2)

    assert report.photos_updated == 2


def test_geocode_new_fetch_caches_country_code(tmp_path: Path):
    db = _make_db(tmp_path)
    db.upsert_photo(_gps_photo("photos_library:u1", 37.5285, 127.0552))
    client = FakeClient(
        result=GeocodeResult(country="대한민국", city="서울", district="강남구", country_code="KR")
    )

    geocode_photos(db, client)

    assert db.get_geocode_cache(quantize(37.5285), quantize(127.0552)) == GeocodeCacheEntry(
        country="대한민국", city="서울", district="강남구", country_code="KR"
    )


def test_backfill_country_codes_refetches_only_missing_cells(tmp_path: Path):
    db = _make_db(tmp_path)
    db.upsert_geocode_cache(37529, 127055, "대한민국", "서울", "강남구", None)  # 대상
    db.upsert_geocode_cache(41902, 12496, "이탈리아", "로마", None, "IT")  # 기채움
    db.upsert_geocode_cache(0, -160000, None, None, None, None)  # negative
    client = FakeClient(
        result=GeocodeResult(country="대한민국", city="서울", district="강남구", country_code="KR")
    )

    report = backfill_country_codes(db, client)

    assert client.calls == [(37.529, 127.055)]
    assert report.cells_updated == 1
    assert report.errors == 0
    assert db.get_geocode_cache(37529, 127055).country_code == "KR"
    # 지명 필드는 백필이 건드리지 않는다.
    refilled = db.get_geocode_cache(37529, 127055)
    assert (refilled.country, refilled.city, refilled.district) == ("대한민국", "서울", "강남구")


def test_backfill_country_codes_aborts_after_consecutive_errors(tmp_path: Path):
    db = _make_db(tmp_path)
    for i in range(10):
        db.upsert_geocode_cache(10000 + i, 100000 + i, "몽골", None, None, None)
    client = FakeClient(error=GeocodeError("HTTP 500"))

    report = backfill_country_codes(db, client, max_consecutive_errors=3)

    assert report.aborted is True
    assert report.errors == 3
    assert len(client.calls) == 3

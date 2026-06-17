import sqlite3
from pathlib import Path

import pytest

from eddr.db.repository import EddrDatabase, GeocodeCacheEntry, PhotoRecord


def test_photo_caption_and_vector_state_round_trip(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    db.upsert_photo(
        PhotoRecord(
            id="local:abc",
            source="local",
            source_uri="/photos/a.jpg",
            image_path="/photos/a.jpg",
            content_hash="abc",
            perceptual_hash="ff00",
            taken_at="2020-06-20T10:00:00+00:00",
            latitude=37.1,
            longitude=127.2,
            width=1200,
            height=800,
            indexing_status="meta_done",
        )
    )

    assert db.count_photos() == 1
    assert [p.id for p in db.pending_vision_photos(limit=10)] == ["local:abc"]

    db.upsert_caption(
        photo_id="local:abc",
        model_id="gemma4:e2b",
        lang="en",
        text="A night beach scene with vehicle light trails.",
    )
    db.upsert_embedding_record(
        photo_id="local:abc",
        kind="caption_text",
        model_id="qwen3-embedding:8b",
        vector_id="caption_text:local:abc:qwen3-embedding:8b",
        dimensions=4096,
    )
    db.update_status("local:abc", "caption_done")

    row = db.get_photo("local:abc")
    assert row is not None
    assert row.indexing_status == "caption_done"
    assert db.pending_vision_photos(limit=10) == []
    assert db.count_captions() == 1
    assert db.count_embeddings(kind="caption_text") == 1


def test_pending_vision_photos_excludes_skipped_video(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.upsert_photo(
        PhotoRecord(
            id="local:img",
            source="local",
            source_uri="/photos/a.jpg",
            image_path="/photos/a.jpg",
            indexing_status="meta_done",
        )
    )
    db.upsert_photo(
        PhotoRecord(
            id="local:vid",
            source="local",
            source_uri="/photos/clip.mov",
            image_path="/photos/clip.mov",
            indexing_status="skipped_video",
        )
    )

    assert [p.id for p in db.pending_vision_photos(limit=10)] == ["local:img"]


def test_upsert_photo_meta_reload_keeps_caption_done(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    record = PhotoRecord(
        id="local:abc",
        source="local",
        source_uri="/photos/a.jpg",
        image_path="/photos/a.jpg",
        indexing_status="meta_done",
    )
    db.upsert_photo(record)
    db.update_status("local:abc", "caption_done")

    db.upsert_photo(record)

    assert db.get_photo("local:abc").indexing_status == "caption_done"
    assert db.pending_vision_photos(limit=10) == []


def test_upsert_photo_preserves_manual_coordinates(tmp_path: Path):
    """재적재가 수동 지정 좌표를 리셋하지 않는다 (ADR-0009 §4, M4 품질 리뷰 C1).

    소스 레코드는 GPS 무 사진에서 latitude=None을 싣고 오므로, 무조건
    덮어쓰면 manual 좌표가 NULL로 돌아가 위치 미상 그룹에 재등장한다.
    """
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    record = PhotoRecord(
        id="local:noloc",
        source="local",
        source_uri="/photos/n.jpg",
        image_path="/photos/n.jpg",
        indexing_status="meta_done",
    )
    db.upsert_photo(record)
    db.update_photo_location(["local:noloc"], 36.605, 126.618)

    db.upsert_photo(record)  # 재적재 — 소스에는 여전히 GPS 없음

    photo = db.get_photo("local:noloc")
    assert (photo.latitude, photo.longitude) == (36.605, 126.618)
    assert db.no_location_day_groups() == []  # 위치 미상으로 재등장하지 않음

    # 대조: manual이 아닌 행은 기존 의미론(소스 값으로 갱신) 유지
    exif = PhotoRecord(
        id="local:exif",
        source="local",
        source_uri="/photos/e.jpg",
        image_path="/photos/e.jpg",
        indexing_status="meta_done",
        latitude=37.5,
        longitude=127.0,
    )
    db.upsert_photo(exif)
    db.upsert_photo(
        PhotoRecord(
            id="local:exif",
            source="local",
            source_uri="/photos/e.jpg",
            image_path="/photos/e.jpg",
            indexing_status="meta_done",
            latitude=35.1,
            longitude=129.0,
        )
    )
    assert db.get_photo("local:exif").latitude == 35.1


@pytest.mark.parametrize(
    ("existing", "incoming", "expected"),
    [
        ("skipped_video", "meta_done", "skipped_video"),
        ("trip_assigned", "meta_done", "trip_assigned"),
        ("caption_done", "missing_image", "caption_done"),
        ("missing_image", "meta_done", "meta_done"),
        ("meta_done", "missing_image", "missing_image"),
    ],
)
def test_upsert_photo_status_on_reload(tmp_path: Path, existing: str, incoming: str, expected: str):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    db.upsert_photo(
        PhotoRecord(
            id="local:abc",
            source="local",
            source_uri="/photos/a.jpg",
            indexing_status="meta_done",
        )
    )
    db.update_status("local:abc", existing)

    db.upsert_photo(
        PhotoRecord(
            id="local:abc",
            source="local",
            source_uri="/photos/a.jpg",
            indexing_status=incoming,
        )
    )

    assert db.get_photo("local:abc").indexing_status == expected


LEGACY_PHOTOS_DDL = """
    CREATE TABLE photos (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        source_uri TEXT NOT NULL,
        image_path TEXT,
        content_hash TEXT,
        perceptual_hash TEXT,
        taken_at TEXT,
        latitude REAL,
        longitude REAL,
        width INTEGER,
        height INTEGER,
        camera_make TEXT,
        camera_model TEXT,
        indexing_status TEXT NOT NULL DEFAULT 'meta_done',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(source, source_uri)
    );
"""


def _table_names(db: EddrDatabase) -> set[str]:
    with db.connect() as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def _photo_columns(db: EddrDatabase) -> set[str]:
    with db.connect() as conn:
        rows = conn.execute("PRAGMA table_info(photos)").fetchall()
    return {row["name"] for row in rows}


def test_initialize_creates_enrichment_tables(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    assert {"trips", "trip_countries", "daily_radius_areas", "geocode_cache"} <= _table_names(db)
    assert {
        "country",
        "city",
        "district",
        "trip_id",
        "duplicate_of",
        "taken_at_raw",
    } <= _photo_columns(db)


def test_initialize_migrates_legacy_photos_schema(tmp_path: Path):
    path = tmp_path / "eddr.sqlite"
    legacy = sqlite3.connect(path)
    legacy.executescript(LEGACY_PHOTOS_DDL)
    legacy.execute(
        "INSERT INTO photos (id, source, source_uri, indexing_status)"
        " VALUES ('local:abc', 'local', '/photos/a.jpg', 'caption_done')"
    )
    legacy.commit()
    legacy.close()

    db = EddrDatabase(path)
    db.initialize()

    assert {
        "country",
        "city",
        "district",
        "trip_id",
        "duplicate_of",
        "taken_at_raw",
    } <= _photo_columns(db)
    row = db.get_photo("local:abc")
    assert row is not None
    assert row.indexing_status == "caption_done"
    assert row.country is None
    assert row.duplicate_of is None


def test_initialize_is_idempotent(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.initialize()

    assert db.count_photos() == 0


LEGACY_GEOCODE_CACHE_DDL = """
    CREATE TABLE geocode_cache (
        lat_quantized INTEGER NOT NULL,
        lng_quantized INTEGER NOT NULL,
        country TEXT,
        city TEXT,
        district TEXT,
        source TEXT NOT NULL DEFAULT 'nominatim',
        fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(lat_quantized, lng_quantized)
    );
"""


def test_initialize_adds_country_code_to_legacy_geocode_cache(tmp_path: Path):
    path = tmp_path / "eddr.sqlite"
    legacy = sqlite3.connect(path)
    legacy.executescript(LEGACY_GEOCODE_CACHE_DDL)
    legacy.execute(
        "INSERT INTO geocode_cache (lat_quantized, lng_quantized, country, city, district)"
        " VALUES (37529, 127055, '대한민국', '서울', '강남구')"
    )
    legacy.commit()
    legacy.close()

    db = EddrDatabase(path)
    db.initialize()

    assert db.get_geocode_cache(37529, 127055) == GeocodeCacheEntry(
        country="대한민국", city="서울", district="강남구", country_code=None
    )


def test_geocode_cache_round_trips_country_code(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    db.upsert_geocode_cache(37529, 127055, "대한민국", "서울", "강남구", "KR")

    assert db.get_geocode_cache(37529, 127055) == GeocodeCacheEntry(
        country="대한민국", city="서울", district="강남구", country_code="KR"
    )


def test_geocode_cells_missing_country_code_excludes_negative_and_filled(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.upsert_geocode_cache(37529, 127055, "대한민국", "서울", "강남구", None)  # 백필 대상
    db.upsert_geocode_cache(41902, 12496, "이탈리아", "로마", None, "IT")  # 이미 채움
    db.upsert_geocode_cache(0, -160000, None, None, None, None)  # negative cache (바다)

    assert db.geocode_cells_missing_country_code() == [(37529, 127055)]


def test_update_geocode_cache_country_code(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.upsert_geocode_cache(37529, 127055, "대한민국", "서울", "강남구", None)

    db.update_geocode_cache_country_code(37529, 127055, "KR")

    assert db.get_geocode_cache(37529, 127055) == GeocodeCacheEntry(
        country="대한민국", city="서울", district="강남구", country_code="KR"
    )


def _trip_photo(
    photo_id: str,
    taken_at: str | None,
    lat: float | None = None,
    lng: float | None = None,
    status: str = "caption_done",
) -> PhotoRecord:
    return PhotoRecord(
        id=photo_id,
        source="photos_library",
        source_uri=photo_id,
        taken_at=taken_at,
        latitude=lat,
        longitude=lng,
        indexing_status=status,
    )


def _insert_june_trip(db: EddrDatabase, name: str = "여행") -> str:
    trip_id = "trip_20190601_01"
    db.insert_trip(trip_id, name, "2019-06-01 09:00:00", "2019-06-03 18:00:00", 37.8, 128.9)
    return trip_id


def test_photos_for_trip_clustering_excludes_videos_and_requires_gps_and_time(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.upsert_photo(_trip_photo("pl:gps", "2019-06-02T10:00:00+00:00", 37.8, 128.9))
    db.upsert_photo(
        _trip_photo("pl:video", "2019-06-02T11:00:00+00:00", 37.8, 128.9, "skipped_video")
    )
    db.upsert_photo(_trip_photo("pl:nogps", "2019-06-02T12:00:00+00:00"))
    db.upsert_photo(_trip_photo("pl:notime", None, 37.8, 128.9))
    db.upsert_photo(_trip_photo("pl:early", "2019-06-01T09:00:00+00:00", 37.8, 128.9))

    rows = db.photos_for_trip_clustering()

    assert [row.id for row in rows] == ["pl:early", "pl:gps"]


def test_assign_trip_by_timerange_assigns_and_transitions_status(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    _insert_june_trip(db, name="강릉시 여행 2019-06")
    # 포맷 혼재: aware(+00:00)·naive 모두 naive UTC 경계와 비교돼야 한다.
    db.upsert_photo(_trip_photo("pl:aware", "2019-06-02T10:00:00+00:00", 37.8, 128.9))
    db.upsert_photo(_trip_photo("local:naive", "2019-06-02T11:30:00", 37.8, 128.9))
    # 기간 내 no-GPS도 배정된다 (PLAN §8).
    db.upsert_photo(_trip_photo("pl:nogps", "2019-06-02T20:00:00"))
    db.upsert_photo(
        _trip_photo("pl:video", "2019-06-02T12:00:00+00:00", 37.8, 128.9, "skipped_video")
    )
    db.upsert_photo(_trip_photo("pl:meta", "2019-06-02T13:00:00+00:00", 37.8, 128.9, "meta_done"))
    db.upsert_photo(_trip_photo("pl:outside", "2019-06-09T10:00:00+00:00", 37.8, 128.9))

    assigned = db.assign_trip_by_timerange(
        "trip_20190601_01", "2019-06-01 09:00:00", "2019-06-03 18:00:00"
    )

    assert assigned == 4  # aware + naive + nogps + meta (video·기간밖 제외)
    assert db.get_photo("pl:aware").trip_id == "trip_20190601_01"
    assert db.get_photo("pl:aware").indexing_status == "trip_assigned"
    assert db.get_photo("local:naive").trip_id == "trip_20190601_01"
    assert db.get_photo("pl:nogps").trip_id == "trip_20190601_01"
    # 영상은 배정·전이 모두 없음 (사용자 결정: 완전 제외).
    assert db.get_photo("pl:video").trip_id is None
    assert db.get_photo("pl:video").indexing_status == "skipped_video"
    # caption_done 전 단계는 trip_id만 받고 status는 유지 (체크포인트 의미 보존).
    assert db.get_photo("pl:meta").trip_id == "trip_20190601_01"
    assert db.get_photo("pl:meta").indexing_status == "meta_done"
    assert db.get_photo("pl:outside").trip_id is None


def test_reset_trip_assignments_restores_status_and_clears_tables(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    _insert_june_trip(db)
    db.insert_trip_countries("trip_20190601_01", ["KR"])
    db.upsert_photo(_trip_photo("pl:a", "2019-06-02T10:00:00+00:00", 37.8, 128.9))
    db.assign_trip_by_timerange("trip_20190601_01", "2019-06-01 09:00:00", "2019-06-03 18:00:00")

    db.reset_trip_assignments()

    assert db.get_photo("pl:a").trip_id is None
    assert db.get_photo("pl:a").indexing_status == "caption_done"
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM trips").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM trip_countries").fetchone()[0] == 0


def test_finalize_trip_photo_counts_excludes_duplicates(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    _insert_june_trip(db)
    db.upsert_photo(_trip_photo("pl:canon", "2019-06-02T10:00:00+00:00", 37.8, 128.9))
    db.upsert_photo(_trip_photo("local:dup", "2019-06-02T10:00:00", 37.8, 128.9))
    with db.connect() as conn:
        conn.execute("UPDATE photos SET duplicate_of = 'pl:canon' WHERE id = 'local:dup'")
    db.assign_trip_by_timerange("trip_20190601_01", "2019-06-01 09:00:00", "2019-06-03 18:00:00")

    db.finalize_trip_photo_counts()

    with db.connect() as conn:
        row = conn.execute("SELECT photo_count FROM trips WHERE id = 'trip_20190601_01'").fetchone()
    assert row["photo_count"] == 1  # dup은 배정은 되지만 노출 수에선 제외


def test_photo_record_round_trips_enrichment_fields(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.upsert_photo(PhotoRecord(id="local:abc", source="local", source_uri="/photos/a.jpg"))
    db.upsert_photo(PhotoRecord(id="photos_library:u1", source="photos_library", source_uri="u1"))

    with db.connect() as conn:
        conn.execute(
            "UPDATE photos SET country = '대한민국', city = '서울', district = '강남구',"
            " duplicate_of = 'photos_library:u1' WHERE id = 'local:abc'"
        )

    row = db.get_photo("local:abc")
    assert (row.country, row.city, row.district) == ("대한민국", "서울", "강남구")
    assert row.duplicate_of == "photos_library:u1"
    assert db.get_photo("photos_library:u1").duplicate_of is None


def test_upsert_photo_preserves_existing_caption(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    record = PhotoRecord(
        id="takeout:def",
        source="google_takeout",
        source_uri="2011/photo.jpg",
        image_path="/staged/def.jpg",
        content_hash="def",
        taken_at="2011-04-02T15:14:20+00:00",
        width=640,
        height=480,
        indexing_status="meta_done",
    )
    db.upsert_photo(record)
    db.upsert_caption("takeout:def", "gemma4:e2b", "en", "first caption")

    db.upsert_photo(
        PhotoRecord(
            **{
                **record.__dict__,
                "width": 800,
                "height": 600,
                "indexing_status": "caption_done",
            }
        )
    )

    assert db.get_photo("takeout:def").width == 800
    assert db.count_captions() == 1


def _query_layer_db(tmp_path: Path) -> EddrDatabase:
    """질의 레이어 테스트용 DB — trip 1개·국내외 사진·duplicate·영상·GPS 무 사진."""
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    def add(photo_id: str, **kwargs) -> None:
        defaults = {
            "source": "photos_library",
            "source_uri": photo_id,
            "image_path": f"/photos/{photo_id}.jpg",
            "indexing_status": "caption_done",
        }
        db.upsert_photo(PhotoRecord(id=photo_id, **{**defaults, **kwargs}))

    add("p1", taken_at="2018-04-01 10:00:00", latitude=41.9, longitude=12.5)
    add("p2", taken_at="2018-04-02 11:00:00", latitude=43.7, longitude=11.2)
    add("p3", taken_at="2018-04-03 12:00:00")  # GPS·geocode 없음 — trip 기간 내
    add("p4", taken_at="2020-01-05 09:00:00", latitude=37.5, longitude=126.9)
    add("p5", taken_at="2021-07-01 08:00:00", source="local", indexing_status="meta_done")
    add("vid", indexing_status="skipped_video")
    db.update_photo_geo("p1", "이탈리아", "로마", None)
    db.update_photo_geo("p2", "이탈리아", "피렌체", None)
    db.update_photo_geo("p4", "대한민국", "서울특별시", "마포구")
    db.upsert_caption("p4", "gemma4:e2b", "en", "A wedding cake on a table.")

    # p5는 p4의 cross-source 사본
    with db.connect() as conn:
        conn.execute("UPDATE photos SET duplicate_of = 'p4' WHERE id = 'p5'")

    db.insert_trip(
        "trip_20180401_01",
        "이탈리아 여행 2018-04",
        "2018-04-01 00:00:00",
        "2018-04-04 00:00:00",
        42.0,
        12.0,
    )
    db.insert_trip_countries("trip_20180401_01", ["IT"])
    db.assign_trip_by_timerange("trip_20180401_01", "2018-04-01 00:00:00", "2018-04-04 00:00:00")
    db.finalize_trip_photo_counts()
    return db


def test_query_photos_applies_filters_dedup_and_location_first_order(tmp_path: Path):
    from eddr.db.repository import PhotoQueryFilters

    db = _query_layer_db(tmp_path)

    by_country = db.query_photos(PhotoQueryFilters(countries=("이탈리아",)), limit=10)
    assert [p.id for p in by_country] == ["p2", "p1"]  # 최신순

    in_trip = db.query_photos(PhotoQueryFilters(trip_id="trip_20180401_01"), limit=10)
    # trip 내는 시간 오름차순 + geocode 있는 사진 우선, GPS 무(p3)는 하단
    assert [p.id for p in in_trip] == ["p1", "p2", "p3"]

    everything = db.query_photos(PhotoQueryFilters(), limit=50)
    ids = [p.id for p in everything]
    assert "p5" not in ids  # duplicate_of 마킹 행 미노출
    assert "vid" not in ids  # 영상 미노출

    by_caption = db.query_photos(PhotoQueryFilters(caption_match="wedding"), limit=10)
    assert [p.id for p in by_caption] == ["p4"]

    by_city_district = db.query_photos(PhotoQueryFilters(cities=("마포",)), limit=10)
    assert [p.id for p in by_city_district] == ["p4"]  # district 매칭

    assert len(db.query_photos(PhotoQueryFilters(), limit=2)) == 2  # limit 강제


def test_filter_photo_ids_preserves_order_and_drops_filtered(tmp_path: Path):
    from eddr.db.repository import PhotoQueryFilters

    db = _query_layer_db(tmp_path)
    candidates = ["p3", "p5", "p1", "vid", "missing", "p4"]

    passed = db.filter_photo_ids(candidates, PhotoQueryFilters())
    assert passed == ["p3", "p1", "p4"]  # 거리순 입력 순서 보존, dup·영상·미존재 제거

    only_italy = db.filter_photo_ids(candidates, PhotoQueryFilters(countries=("이탈리아",)))
    assert only_italy == ["p1"]

    assert db.filter_photo_ids([], PhotoQueryFilters()) == []


def test_place_filters_combine_as_single_or_group(tmp_path: Path):
    # countries·cities·trip_ids는 단일 OR 그룹 (ADR-0009, prd §6-c).
    from eddr.db.repository import PhotoQueryFilters

    db = _query_layer_db(tmp_path)

    # 국가 OR 도시 — 별개 AND였다면 교집합이 비어야 하지만 OR라 합집합이다.
    country_or_city = db.query_photos(
        PhotoQueryFilters(countries=("대한민국",), cities=("로마",)), limit=10
    )
    assert {p.id for p in country_or_city} == {"p4", "p1"}

    # 국가 OR trip_ids — geocode 무 사진(p3)이 trip 소속으로 함께 잡힌다.
    with_trip = db.query_photos(
        PhotoQueryFilters(countries=("이탈리아",), trip_ids=("trip_20180401_01",)), limit=10
    )
    assert {p.id for p in with_trip} == {"p1", "p2", "p3"}

    # trip_ids 단독 IN 매칭 + 미존재 trip은 무효과.
    only_trip = db.query_photos(
        PhotoQueryFilters(trip_ids=("trip_20180401_01", "trip_unknown")), limit=10
    )
    assert {p.id for p in only_trip} == {"p1", "p2", "p3"}

    # 단수 trip_id(직접 지정)는 독립 AND 조건으로 유지 — OR 그룹과 교차한다.
    and_trip = db.query_photos(
        PhotoQueryFilters(countries=("대한민국",), trip_id="trip_20180401_01"), limit=10
    )
    assert and_trip == []


def test_trip_ids_for_places_matches_photo_place_names(tmp_path: Path):
    db = _query_layer_db(tmp_path)

    # 국가명·도시명(부분 일치) 모두 photos의 한국어 지명으로 자기일관 매칭.
    assert db.trip_ids_for_places(countries=("이탈리아",)) == ["trip_20180401_01"]
    assert db.trip_ids_for_places(cities=("로마",)) == ["trip_20180401_01"]
    # p4(마포구)는 trip 미배정 — trip_id IS NOT NULL로 걸러진다.
    assert db.trip_ids_for_places(cities=("마포",)) == []
    assert db.trip_ids_for_places(countries=("몽골",)) == []
    assert db.trip_ids_for_places() == []


def test_query_trips_matches_name_or_photo_country_and_date_overlap(tmp_path: Path):
    db = _query_layer_db(tmp_path)

    by_name = db.query_trips(countries=("이탈리아",))
    assert [t.id for t in by_name] == ["trip_20180401_01"]
    assert by_name[0].photo_count == 3

    by_overlap = db.query_trips(date_from="2018-04-03 00:00:00", date_to="2018-05-01 00:00:00")
    assert [t.id for t in by_overlap] == ["trip_20180401_01"]

    assert db.query_trips(countries=("몽골",)) == []
    assert db.query_trips(date_from="2019-01-01 00:00:00") == []


def test_trip_detail_helpers_and_indexing_stats(tmp_path: Path):
    db = _query_layer_db(tmp_path)

    trip = db.get_trip_record("trip_20180401_01")
    assert trip is not None and trip.name == "이탈리아 여행 2018-04"
    assert db.get_trip_record("trip_unknown") is None
    assert db.trip_country_codes("trip_20180401_01") == ["IT"]
    assert db.trip_top_cities("trip_20180401_01") == ["로마", "피렌체"]

    stats = db.indexing_stats()
    # 영상·duplicate 제외: p1-p4 = 4건 모집단, p5(meta_done)는 dup라 분모에서도 제외
    assert (stats.ready, stats.total) == (4, 4)


def test_captions_fts_bm25_search_and_sync(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    for pid, text in (
        ("p1", "A basalt coastline with black volcanic rocks."),
        ("p2", "A road through mountains with a parked car."),
        ("p3", "Basalt columns near the basalt beach, basalt everywhere."),
    ):
        db.upsert_photo(PhotoRecord(id=pid, source="local", source_uri=pid))
        db.upsert_caption(pid, "gemma4:e2b", "en", text)

    # BM25 관련도순 — 'basalt' 빈도가 높은 p3가 상위
    assert db.search_caption_photo_ids('"basalt"', limit=10) == ["p3", "p1"]
    # porter stemming — 'roads'가 'road' 캡션에 매칭
    assert db.search_caption_photo_ids('"roads"', limit=10) == ["p2"]
    # UPDATE 트리거 동기화 — 캡션 교체 후 옛 텍스트는 더 이상 매칭 안 됨
    db.upsert_caption("p3", "gemma4:e2b", "en", "A snowy field.")
    assert db.search_caption_photo_ids('"basalt"', limit=10) == ["p1"]
    # 재초기화 멱등 — 인덱스 유지
    db.initialize()
    assert db.search_caption_photo_ids('"snowy"', limit=10) == ["p3"]


def test_captions_fts_rebuild_backfills_preexisting_rows(tmp_path: Path):
    # 실DB 최초 마이그레이션 시나리오 — 캡션 데이터는 있는데 FTS 색인이 없는 상태.
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.upsert_photo(PhotoRecord(id="p1", source="local", source_uri="p1"))
    db.upsert_caption("p1", "gemma4:e2b", "en", "A snowy unicorn field.")
    with db.connect() as conn:
        conn.executescript(
            """
            DROP TRIGGER captions_fts_ai;
            DROP TRIGGER captions_fts_au;
            DROP TRIGGER captions_fts_ad;
            DROP TABLE captions_fts;
            """
        )
    db.initialize()
    # external-content FTS의 count(*)는 content 테이블을 비추므로 행 수가 같아
    # 보인다 — 실색인(docsize) 기준으로 감지해 rebuild해야 검색이 된다.
    assert db.search_caption_photo_ids('"unicorn"', limit=10) == ["p1"]


def test_notes_crud_round_trip_and_cascade(tmp_path: Path):
    """notes CRUD — 사진별 1메모 upsert·삭제 반환값·photos 삭제 CASCADE (D26 M5)."""
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.upsert_photo(PhotoRecord(id="p1", source="local", source_uri="p1"))

    assert db.get_note("p1") is None
    db.upsert_note("p1", "엄마가 좋아하던 벚꽃길")
    assert db.get_note("p1") == "엄마가 좋아하던 벚꽃길"
    db.upsert_note("p1", "수정된 메모")  # 사진별 1메모 — PK 충돌 시 교체
    assert db.get_note("p1") == "수정된 메모"

    assert db.delete_note("p1") is True
    assert db.get_note("p1") is None
    assert db.delete_note("p1") is False  # 없는 메모 — 라우트 404 분기용

    db.upsert_note("p1", "메모")
    with db.connect() as conn:
        conn.execute("DELETE FROM photos WHERE id = 'p1'")
    assert db.get_note("p1") is None  # ON DELETE CASCADE


def test_no_location_day_groups_value_sort(tmp_path: Path):
    """가치순 정렬 — trip 있는 그룹 먼저, 같은 tier 안에서 count 내림, 동률은 date DESC.

    픽스처:
        - A: trip 없음, count=1, date=2024-02-10 (trip 범위 밖, 최신)
        - B: trip 없음, count=1, date=2024-02-09 (trip 범위 밖, 동률 → date DESC으로 A>B)
        - C: trip 있음, count=2, date=2024-01-01 (oldest)
        - D: trip 있음, count=3, date=2024-01-03 (최다장수 → 최우선)

    기대 순서: D(trip,3장,01-03) → C(trip,2장,01-01) → A(no trip,1장,02-10) → B(no trip,1장,02-09)
        trip tier: D count 많아 선행, C 후행
        no-trip tier: A·B count 동률 → date DESC → A>B
    """
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    # 여행 하나 삽입 (01-01 ~ 01-05 범위)
    db.insert_trip(
        "trip_01", "제주도 여행", "2023-12-31 00:00:00", "2024-01-06 00:00:00", 33.5, 126.5
    )

    def add(photo_id: str, taken_at: str) -> None:
        db.upsert_photo(
            PhotoRecord(
                id=photo_id,
                source="local",
                source_uri=photo_id,
                taken_at=taken_at,
                indexing_status="caption_done",
            )
        )

    # A: trip 범위 밖, count=1, date=2024-02-10
    add("a1", "2024-02-10T10:00:00+09:00")

    # B: trip 범위 밖, count=1, date=2024-02-09 (A와 동률 → date DESC 으로 A가 먼저)
    add("b1", "2024-02-09T10:00:00+09:00")

    # C: trip 있음, count=2, date=2024-01-01
    add("c1", "2024-01-01T08:00:00+09:00")
    add("c2", "2024-01-01T09:00:00+09:00")

    # D: trip 있음, count=3, date=2024-01-03 (count 가장 많음 → 최우선)
    add("d1", "2024-01-03T08:00:00+09:00")
    add("d2", "2024-01-03T09:00:00+09:00")
    add("d3", "2024-01-03T10:00:00+09:00")

    db.assign_trip_by_timerange("trip_01", "2023-12-31 00:00:00", "2024-01-06 00:00:00")

    groups = db.no_location_day_groups()
    dates = [g["date"] for g in groups]

    assert dates == ["2024-01-03", "2024-01-01", "2024-02-10", "2024-02-09"], (
        f"가치순 기대 [D, C, A, B] 순서 불일치: {dates}"
    )
    # trip 소속 그룹은 trip_name이 있어야 한다
    assert groups[0]["trip_name"] == "제주도 여행"
    assert groups[1]["trip_name"] == "제주도 여행"
    assert groups[2]["trip_name"] is None
    assert groups[3]["trip_name"] is None


def test_embedding_vector_ids_and_delete_by_kind(tmp_path: Path):
    """note_text 임베딩 행 조회·삭제 — 다른 kind(caption_text)는 비파괴 (D26 M5)."""
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.upsert_photo(PhotoRecord(id="p1", source="local", source_uri="p1"))
    db.upsert_embedding_record("p1", "caption_text", "m", "caption_text:p1:m", 3)
    db.upsert_embedding_record("p1", "note_text", "m", "note_text:p1:m", 3)

    assert db.embedding_vector_ids("p1", "note_text") == ["note_text:p1:m"]
    assert db.embedding_vector_ids("p1", "nope") == []

    db.delete_embedding_records("p1", "note_text")
    assert db.embedding_vector_ids("p1", "note_text") == []
    assert db.count_embeddings(kind="caption_text") == 1


def test_get_latest_captions_for_ids_matches_single(tmp_path: Path):
    """배치 캡션 조회가 단건 get_latest_caption과 동일 결과를 준다 (N+1 제거).

    p1: 캡션 2건(최신 generated_at 우선) · p2: 1건 · p3: 캡션 없음.
    """
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.upsert_photo(PhotoRecord(id="p1", source="local", source_uri="p1"))
    db.upsert_photo(PhotoRecord(id="p2", source="local", source_uri="p2"))
    db.upsert_photo(PhotoRecord(id="p3", source="local", source_uri="p3"))

    db.upsert_caption("p1", "gemma4:e2b", "en", "old p1")
    # 더 최신 generated_at의 재캡션 — 명시 타임스탬프로 동일-초 tie 회피
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO captions(photo_id, model_id, lang, text, generated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("p1", "gemma4:31b", "en", "new p1", "2030-01-01 00:00:00"),
        )
    db.upsert_caption("p2", "gemma4:e2b", "en", "only p2")

    batch = db.get_latest_captions_for_ids(["p1", "p2", "p3"])

    # 단건과 정확히 일치 (최신 우선)
    assert batch.get("p1") == db.get_latest_caption("p1") == "new p1"
    assert batch.get("p2") == db.get_latest_caption("p2") == "only p2"
    # 캡션 없는 사진은 키 부재 (단건은 None)
    assert "p3" not in batch
    assert db.get_latest_caption("p3") is None
    # 빈 입력 → 빈 dict
    assert db.get_latest_captions_for_ids([]) == {}


def test_prune_index_errors_deletes_resolved_only(tmp_path: Path):
    """산출물이 생긴 사진의 vision·geocode 에러행만 삭제하고 나머지는 보존한다.

    pc(캡션 있음)·pg(geocode 됨)의 에러는 삭제, pn·png(미해소)와 photo_id
    없는 manual_location은 보존.
    """
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    for pid in ("pc", "pn", "pg", "png"):
        db.upsert_photo(PhotoRecord(id=pid, source="local", source_uri=pid))
    db.upsert_caption("pc", "gemma4:e2b", "en", "cap")
    db.update_photo_geo("pg", "대한민국", "서울", None)

    db.record_error("pc", "vision", "old fail")  # 해소(캡션) → 삭제
    db.record_error("pn", "vision", "still fail")  # 미해소 → 보존
    db.record_error("pg", "geocode", "old fail")  # 해소(geocode) → 삭제
    db.record_error("png", "geocode", "still")  # 미해소 → 보존
    db.record_error(None, "manual_location", "x")  # 사진 무관 → 보존

    deleted = db.prune_index_errors()

    assert deleted == 2
    with db.connect() as conn:
        remaining = {
            (row["photo_id"], row["stage"])
            for row in conn.execute("SELECT photo_id, stage FROM index_errors").fetchall()
        }
    assert remaining == {("pn", "vision"), ("png", "geocode"), (None, "manual_location")}
    # 멱등: 재실행 시 추가 삭제 없음
    assert db.prune_index_errors() == 0

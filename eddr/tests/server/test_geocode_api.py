"""위치 미상/수동 지오코딩 API 계약 검증 — no-location 그룹·프록시·location PUT (D26 M4)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eddr.db.repository import EddrDatabase, PhotoRecord
from eddr.geocode.nominatim import GeocodeError, GeocodeResult, SearchCandidate
from eddr.query.tools import QueryService
from eddr.server.app import create_app
from eddr.server.deps import AppState, ServerConfig
from tests.query.test_tools import make_db

KAESIMSA = SearchCandidate(
    name="개심사, 개심사로, 운산면, 서산시, 충청남도, 대한민국",
    latitude=36.6053,
    longitude=126.6182,
    type="place_of_worship",
    address=GeocodeResult(country="대한민국", city="서산시", district="운산면", country_code="KR"),
)


class FakeGeocoder:
    """NominatimClient 대역 — 네트워크 없이 search·reverse 호출을 기록한다."""

    def __init__(self, candidates=(), fail=False):
        self.candidates = list(candidates)
        self.fail = fail
        self.search_queries: list[str] = []
        self.reverse_calls: list[tuple[float, float]] = []

    def search(self, query: str, limit: int = 5) -> list[SearchCandidate]:
        if self.fail:
            raise GeocodeError("nominatim down")
        self.search_queries.append(query)
        return self.candidates[:limit]

    def reverse(self, lat: float, lng: float) -> GeocodeResult:
        if self.fail:
            raise GeocodeError("nominatim down")
        self.reverse_calls.append((lat, lng))
        return GeocodeResult(
            country="대한민국", city="서산시", district="운산면", country_code="KR"
        )


@pytest.fixture()
def db(tmp_path: Path) -> EddrDatabase:
    """make_db + 위치 미상 경계 행 — 영상·dup·날짜무 제외, 샘플 4컷, DESC 정렬 검증용.

    make_db 기본: p3(2018-04-03, GPS 무, trip 배정 — no-location 대상),
    p5(2021-07-01, GPS 무, duplicate — 제외돼야 한다).
    """
    db = make_db(tmp_path)

    def add(photo_id: str, **kwargs) -> None:
        defaults = {
            "source": "photos_library",
            "source_uri": photo_id,
            "image_path": f"/photos/{photo_id}.jpg",
            "indexing_status": "caption_done",
        }
        db.upsert_photo(PhotoRecord(id=photo_id, **{**defaults, **kwargs}))

    # GPS 없는 영상 — no-location에서 빠져야 한다(skipped_video).
    add("v2", taken_at="2022-01-01T08:00:00+09:00", indexing_status="skipped_video")
    # 날짜조차 없는 사진 — 범위 외(D26-⑥).
    add("n1")
    # 같은 KST 달력일 5장 — count 5·샘플 4(taken_at순) 검증.
    for hour in range(5):
        add(f"d{hour + 1}", taken_at=f"2022-01-01T{9 + hour:02d}:00:00+09:00")
    return db


@pytest.fixture()
def geocoder() -> FakeGeocoder:
    return FakeGeocoder(candidates=[KAESIMSA])


def make_client(tmp_path: Path, db: EddrDatabase, geocoder: FakeGeocoder) -> TestClient:
    config = ServerConfig(
        root=tmp_path, db_path=tmp_path / "eddr.sqlite", chroma_path=tmp_path / "chroma"
    )
    state = AppState(config, QueryService(db), geocoder=geocoder)
    return TestClient(create_app(state))


@pytest.fixture()
def env(tmp_path: Path, db: EddrDatabase, geocoder: FakeGeocoder) -> TestClient:
    return make_client(tmp_path, db, geocoder)


# ── GET /api/photos/no-location ───────────────────────────────────────────


def test_no_location_groups_value_sort_and_boundaries(env):
    body = env.get("/api/photos/no-location").json()
    # d1~d5(5장) + p3(1장) — dup(p5)·영상(v2)·날짜무(n1)·GPS 보유(p1·p2·p4)는 제외.
    assert body["total_photos"] == 6
    # 가치순: p3(trip 있음, count=1) > d1~d5(trip 없음, count=5) — trip 소속이 count보다 우선.
    assert [group["date"] for group in body["groups"]] == ["2018-04-03", "2022-01-01"]


def test_no_location_group_samples_capped_at_four_in_time_order(env):
    groups = {g["date"]: g for g in env.get("/api/photos/no-location").json()["groups"]}
    group = groups["2022-01-01"]
    assert group["count"] == 5
    assert group["sample_photo_ids"] == ["d1", "d2", "d3", "d4"]
    assert group["trip_name"] is None


def test_no_location_group_trip_hint_from_assigned_trip(env):
    groups = {g["date"]: g for g in env.get("/api/photos/no-location").json()["groups"]}
    assert groups["2018-04-03"]["trip_name"] == "이탈리아 여행 2018-04"


# ── GET /api/geocode/search ───────────────────────────────────────────────


def test_geocode_search_proxies_candidates(env, geocoder):
    body = env.get("/api/geocode/search", params={"q": "개심사"}).json()
    assert geocoder.search_queries == ["개심사"]
    assert body == {
        "candidates": [
            {
                "name": KAESIMSA.name,
                "latitude": 36.6053,
                "longitude": 126.6182,
                "type": "place_of_worship",
                "address": {"country": "대한민국", "city": "서산시", "district": "운산면"},
            }
        ]
    }


def test_geocode_search_rejects_blank_or_missing_query(env):
    assert env.get("/api/geocode/search", params={"q": "  "}).status_code == 422
    assert env.get("/api/geocode/search").status_code == 422


def test_geocode_search_maps_nominatim_failure_to_502(tmp_path, db):
    client = make_client(tmp_path, db, FakeGeocoder(fail=True))
    assert client.get("/api/geocode/search", params={"q": "개심사"}).status_code == 502


# ── PUT /api/photos/location ──────────────────────────────────────────────


def test_put_location_bulk_marks_manual_and_fills_address(env, db, geocoder):
    response = env.put(
        "/api/photos/location",
        json={"photo_ids": ["d1", "d2"], "latitude": 36.6054, "longitude": 126.6181},
    )
    assert response.status_code == 200
    assert response.json() == {
        "updated": 2,
        "country": "대한민국",
        "city": "서산시",
        "district": "운산면",
    }
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT latitude, longitude, location_source, country, city, district"
            " FROM photos WHERE id IN ('d1', 'd2')"
        ).fetchall()
    assert len(rows) == 2
    for row in rows:
        assert (row["latitude"], row["longitude"]) == (36.6054, 126.6181)
        assert row["location_source"] == "manual"  # EXIF 유래(NULL)와 구분 (ADR-0009 §4)
        assert (row["country"], row["city"], row["district"]) == ("대한민국", "서산시", "운산면")
    # reverse는 원좌표가 아닌 양자화 셀 중심으로 1회 — 기존 geocode 경로와 동일 규약.
    assert geocoder.reverse_calls == [pytest.approx((36.605, 126.618))]


def test_put_location_second_call_hits_geocode_cache(env, db, geocoder):
    coords = {"latitude": 36.6054, "longitude": 126.6181}
    env.put("/api/photos/location", json={"photo_ids": ["d1"], **coords})
    env.put("/api/photos/location", json={"photo_ids": ["d2"], **coords})
    assert len(geocoder.reverse_calls) == 1  # 같은 셀 — 두 번째는 캐시 적중
    with db.connect() as conn:
        row = conn.execute("SELECT country FROM photos WHERE id = 'd2'").fetchone()
    assert row["country"] == "대한민국"


def test_put_location_keeps_coords_with_null_address_when_nominatim_down(tmp_path, db):
    client = make_client(tmp_path, db, FakeGeocoder(fail=True))
    response = client.put(
        "/api/photos/location",
        json={"photo_ids": ["d1"], "latitude": 36.6, "longitude": 126.6},
    )
    assert response.status_code == 200
    assert response.json() == {"updated": 1, "country": None, "city": None, "district": None}
    with db.connect() as conn:
        row = conn.execute(
            "SELECT latitude, location_source, country FROM photos WHERE id = 'd1'"
        ).fetchone()
        errors = conn.execute(
            "SELECT COUNT(*) FROM index_errors WHERE stage = 'manual_location'"
        ).fetchone()[0]
    assert row["latitude"] == 36.6 and row["location_source"] == "manual"
    assert row["country"] is None  # 셀 미캐시 — 다음 geocode 배치가 재시도
    assert errors == 1


def test_put_location_validation_422(env):
    base = {"photo_ids": ["d1"], "latitude": 36.6, "longitude": 126.6}
    for broken in (
        {**base, "photo_ids": []},
        {**base, "photo_ids": "d1"},
        {**base, "latitude": 91.0},
        {**base, "longitude": -200.0},
        {**base, "latitude": "north"},
        {"photo_ids": ["d1"], "latitude": 36.6},  # longitude 누락
    ):
        assert env.put("/api/photos/location", json=broken).status_code == 422


def test_put_location_shrinks_no_location_groups(env):
    before = env.get("/api/photos/no-location").json()
    env.put(
        "/api/photos/location",
        json={
            "photo_ids": ["d1", "d2", "d3", "d4", "d5"],
            "latitude": 36.6,
            "longitude": 126.6,
        },
    )
    after = env.get("/api/photos/no-location").json()
    assert before["total_photos"] - after["total_photos"] == 5
    assert [group["date"] for group in after["groups"]] == ["2018-04-03"]

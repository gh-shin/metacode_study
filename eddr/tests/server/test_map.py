"""지도/by-date 라우트 계약 검증 — GeoJSON·노출 필터·캐시 헤더·날짜 검증 (D26 M2)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eddr.db.repository import PhotoRecord
from eddr.query.tools import QueryService
from eddr.server.app import create_app
from eddr.server.deps import AppState, ServerConfig
from tests.query.test_tools import make_db


@pytest.fixture()
def env(tmp_path: Path):
    """make_db에 영상 행(skipped_video) 하나를 더한 서버 환경 — 노출 필터 검증용."""
    db = make_db(tmp_path)
    # GPS·날짜 있는 영상 — 노출 모집단에서 빠져야 한다(skipped_video).
    db.upsert_photo(
        PhotoRecord(
            id="v1",
            source="photos_library",
            source_uri="v1",
            image_path="/photos/v1.mov",
            taken_at="2018-04-01 13:00:00",
            latitude=41.0,
            longitude=12.0,
            indexing_status="skipped_video",
        )
    )
    config = ServerConfig(
        root=tmp_path, db_path=tmp_path / "eddr.sqlite", chroma_path=tmp_path / "chroma"
    )
    state = AppState(config, QueryService(db))
    return TestClient(create_app(state))


def test_map_photos_is_geojson_feature_collection(env):
    body = env.get("/api/map/photos").json()
    assert body["type"] == "FeatureCollection"
    feature = body["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Point"
    # 좌표는 [lng, lat] 순서(GeoJSON 규약) — properties에 id·date.
    assert len(feature["geometry"]["coordinates"]) == 2
    assert set(feature["properties"].keys()) == {"id", "date"}


def test_map_photos_excludes_duplicates_and_videos(env):
    features = env.get("/api/map/photos").json()["features"]
    ids = {f["properties"]["id"] for f in features}
    # p1·p2·p4만 노출 — p3(GPS無)·p5(dup)·v1(video)은 제외.
    assert ids == {"p1", "p2", "p4"}


def test_map_photos_coordinates_and_date(env):
    features = env.get("/api/map/photos").json()["features"]
    by_id = {f["properties"]["id"]: f for f in features}
    assert by_id["p4"]["geometry"]["coordinates"] == [126.9, 37.5]  # [lng, lat]
    assert by_id["p1"]["properties"]["date"] == "2018-04-01"


def test_map_photos_sets_private_cache_header(env):
    response = env.get("/api/map/photos")
    assert response.headers["cache-control"] == "private, max-age=300"


def test_by_date_returns_exposed_photos_with_coords(env):
    body = env.get("/api/photos/by-date?date=2018-04-01").json()
    assert body["date"] == "2018-04-01"
    photos = {p["photo_id"]: p for p in body["photos"]}
    assert set(photos) == {"p1"}  # v1(video)은 제외
    assert (photos["p1"]["latitude"], photos["p1"]["longitude"]) == (41.9, 12.5)
    assert photos["p1"]["country"] == "이탈리아" and photos["p1"]["city"] == "로마"


def test_by_date_includes_photos_without_gps(env):
    # p3은 2018-04-03·GPS 없음 — 날짜 상세에 좌표 NULL로 포함돼야 한다.
    body = env.get("/api/photos/by-date?date=2018-04-03").json()
    photos = {p["photo_id"]: p for p in body["photos"]}
    assert set(photos) == {"p3"}
    assert photos["p3"]["latitude"] is None and photos["p3"]["longitude"] is None


def test_by_date_orders_by_taken_at_ascending(env):
    # 같은 날짜에 사진이 여럿이면 taken_at 오름차순 — p1만 있는 날은 단건이라
    # 빈 날짜로 정렬 불변을 확인한다(형식만 검증).
    body = env.get("/api/photos/by-date?date=2099-01-01").json()
    assert body["photos"] == []


def test_by_date_rejects_malformed_date(env):
    assert env.get("/api/photos/by-date?date=2018-7-15").status_code == 422
    assert env.get("/api/photos/by-date?date=oops").status_code == 422


def test_photo_detail_includes_coordinates(env):
    body = env.get("/api/photos/p4").json()
    assert body["photo_id"] == "p4"
    assert (body["latitude"], body["longitude"]) == (37.5, 126.9)


def test_photo_detail_coordinates_follow_duplicate_to_canonical(env):
    # p5는 duplicate_of=p4 — 좌표도 canonical(p4) 행에서 와야 한다.
    body = env.get("/api/photos/p5").json()
    assert body["photo_id"] == "p4"
    assert (body["latitude"], body["longitude"]) == (37.5, 126.9)

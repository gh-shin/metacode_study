"""FastAPI 라우트 계약 검증 — EDDR_ROOT resolve·privacy 스키마·path_health (ADR-0008)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from eddr.query.tools import QueryService
from eddr.server.app import create_app
from eddr.server.deps import AppState, ServerConfig
from tests.query.test_tools import make_db


@pytest.fixture()
def env(tmp_path: Path):
    """make_db 위에 상대경로 실파일(p4) 하나를 얹은 서버 환경 — root=tmp_path."""
    db = make_db(tmp_path)
    real = tmp_path / "imgs" / "p4.png"
    real.parent.mkdir(parents=True)
    Image.new("RGB", (800, 600), (10, 120, 200)).save(real)
    with db.connect() as conn:
        # 상대경로로 교체 — EDDR_ROOT(root=tmp_path) resolve 경로를 태운다 (ADR-0008).
        conn.execute("UPDATE photos SET image_path = 'imgs/p4.png' WHERE id = 'p4'")
    config = ServerConfig(
        root=tmp_path, db_path=tmp_path / "eddr.sqlite", chroma_path=tmp_path / "chroma"
    )
    state = AppState(config, QueryService(db))
    return TestClient(create_app(state)), state


def test_healthz(env):
    client, _ = env
    response = client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_photo_detail_is_service_schema_shaped(env):
    client, _ = env
    body = client.get("/api/photos/p4").json()
    assert body["photo_id"] == "p4"
    assert body["camera_model"] == "iPhone 12"
    assert "wedding" in body["keywords"]
    # 좌표는 노출(ADR-0009 §3, 지도·라이트박스용), 파일 경로는 여전히 미노출.
    assert (body["latitude"], body["longitude"]) == (37.5, 126.9)
    assert "image_path" not in body


def test_photo_detail_follows_duplicate_to_canonical(env):
    client, _ = env
    assert client.get("/api/photos/p5").json()["photo_id"] == "p4"


def test_photo_detail_unknown_is_404(env):
    client, _ = env
    assert client.get("/api/photos/nope").status_code == 404


def test_thumb_resolves_relative_path_and_caches(env):
    client, state = env
    response = client.get("/api/photos/p4/thumb?size=320")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    cached = state.thumb_dir / "p4_320.jpg"
    assert cached.is_file()
    with Image.open(cached) as image:
        assert image.format == "JPEG" and max(image.size) <= 320
    assert client.get("/api/photos/p4/thumb?size=320").status_code == 200  # 캐시 히트


def test_thumb_sets_immutable_cache_header(env):
    client, _ = env
    response = client.get("/api/photos/p4/thumb?size=320")
    assert response.headers["cache-control"] == "private, max-age=86400, immutable"


def test_thumb_rejects_non_whitelisted_size(env):
    client, _ = env
    assert client.get("/api/photos/p4/thumb?size=999").status_code == 422


def test_thumb_missing_source_or_photo_is_404(env):
    client, _ = env
    # p1의 /photos/p1.jpg는 실존하지 않는 절대경로 — resolve 후 파일 부재.
    assert client.get("/api/photos/p1/thumb").status_code == 404
    assert client.get("/api/photos/nope/thumb").status_code == 404


def test_photo_summaries_keeps_order_and_skips_unknown(env):
    client, _ = env
    body = client.get("/api/photos/summary?ids=p4,p5,nope,p1").json()
    assert [photo["photo_id"] for photo in body["photos"]] == ["p4", "p5", "p1"]
    duplicate = body["photos"][1]
    assert duplicate["taken_at"] == "2020-01-05 09:00:00"  # p5 → canonical(p4) 메타
    assert "caption" not in body["photos"][0]  # 경량 응답 — 캡션 N+1 없음


def test_original_streams_source_file_as_attachment(env):
    client, _ = env
    response = client.get("/api/photos/p4/original")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert 'filename="p4.png"' in response.headers["content-disposition"]
    # duplicate는 canonical 원본을 따른다 / 파일 부재·미존재 id는 404.
    assert client.get("/api/photos/p5/original").status_code == 200
    assert client.get("/api/photos/p1/original").status_code == 404
    assert client.get("/api/photos/nope/original").status_code == 404


def test_spa_static_served_when_dist_exists(tmp_path: Path):
    db = make_db(tmp_path)
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>EDDR SPA</body></html>", encoding="utf-8")
    config = ServerConfig(
        root=tmp_path, db_path=tmp_path / "eddr.sqlite", chroma_path=tmp_path / "chroma"
    )
    state = AppState(config, QueryService(db))
    client = TestClient(create_app(state))
    response = client.get("/")
    assert response.status_code == 200 and "EDDR SPA" in response.text
    assert client.get("/api/healthz").status_code == 200  # /api 우선순위 유지


def test_status_reports_stats_stages_and_path_health(env):
    client, _ = env
    body = client.get("/api/status").json()
    assert body["ready"] == 4 and body["total"] == 4  # p5는 duplicate 제외
    assert sum(body["stages"].values()) == 5  # 원시 분포는 duplicate 포함
    health = body["path_health"]
    assert health["sampled"] == 4  # 노출 사진 4장 전부 표본
    assert health["ok"] == 1  # 실파일은 p4 하나
    assert health["healthy"] is False


def test_chat_routes_are_gone(env):
    # 채팅 일괄 삭제 (ADR-0009, prd §6-f) — 구 엔드포인트는 404다.
    client, _ = env
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 404
    assert client.get("/api/chat/history").status_code == 404
    assert client.post("/api/chat/reset").status_code == 404

"""메모 라우트 계약 검증 — upsert+동기 임베딩·embedded:false 폴백·일괄 삭제 (D26 M5, S5)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eddr.query.tools import QueryService
from eddr.server.app import create_app
from eddr.server.deps import AppState, ServerConfig
from tests.query.test_tools import FakeEmbeddingClient, make_db


class FakeNoteChroma:
    """Chroma 메모 컬렉션 대역 — upsert/delete/count를 인메모리로 기록한다."""

    def __init__(self):
        self.items: dict[str, tuple[list[float], str, dict]] = {}

    def upsert(self, ids, embeddings, documents, metadatas):
        for i, vector_id in enumerate(ids):
            self.items[vector_id] = (embeddings[i], documents[i], metadatas[i])

    def delete(self, ids):
        for vector_id in ids:
            self.items.pop(vector_id, None)

    def count(self):
        return len(self.items)

    def query(self, embedding, k, where=None):
        return []


class EmbedClient(FakeEmbeddingClient):
    """라우트가 vector_id·model_id를 만들 때 쓰는 embedding_model을 가진 대역."""

    embedding_model = "qwen3-embedding:8b"


class DownEmbedClient(EmbedClient):
    """ollama 다운 재현 — embed 호출이 ConnectionError를 낸다."""

    def embed_texts(self, texts):
        raise ConnectionError("Failed to connect to Ollama")


def _env(tmp_path: Path, embed_client) -> tuple[TestClient, object, FakeNoteChroma]:
    db = make_db(tmp_path)
    note_store = FakeNoteChroma()
    service = QueryService(db, embedding_client=embed_client)
    config = ServerConfig(
        root=tmp_path, db_path=tmp_path / "eddr.sqlite", chroma_path=tmp_path / "chroma"
    )
    state = AppState(config, service, note_store=note_store)
    return TestClient(create_app(state)), db, note_store


@pytest.fixture()
def env(tmp_path: Path):
    return _env(tmp_path, EmbedClient())


def test_put_note_saves_embeds_and_returns_contract(env):
    client, db, store = env
    response = client.put("/api/photos/p1/note", json={"text": " 엄마가 좋아하던 벚꽃길 "})

    assert response.status_code == 200
    assert response.json() == {
        "photo_id": "p1",
        "text": "엄마가 좋아하던 벚꽃길",  # strip 저장
        "embedded": True,
    }
    assert db.get_note("p1") == "엄마가 좋아하던 벚꽃길"
    vector_id = "note_text:p1:qwen3-embedding:8b"
    assert store.items[vector_id][1] == "엄마가 좋아하던 벚꽃길"  # document = 메모 원문
    assert store.items[vector_id][2] == {"photo_id": "p1"}
    assert db.embedding_vector_ids("p1", "note_text") == [vector_id]

    # 재저장 = upsert — 메모·벡터·임베딩 행 전부 1개 유지(사진별 1메모).
    client.put("/api/photos/p1/note", json={"text": "수정"})
    assert db.get_note("p1") == "수정"
    assert store.count() == 1
    assert db.count_embeddings(kind="note_text") == 1


def test_put_note_rejects_unknown_photo_and_blank_text(env):
    client, db, store = env
    assert client.put("/api/photos/nope/note", json={"text": "x"}).status_code == 404
    assert client.put("/api/photos/p1/note", json={"text": "   "}).status_code == 422
    assert client.put("/api/photos/p1/note", json={"text": 5}).status_code == 422
    assert client.put("/api/photos/p1/note", json={}).status_code == 422
    assert db.get_note("p1") is None
    assert store.count() == 0


def test_put_note_on_duplicate_attaches_to_canonical(env):
    client, db, _ = env
    body = client.put("/api/photos/p5/note", json={"text": "메모"}).json()
    # p5는 p4의 duplicate — 검색 노출 모집단(canonical)에 귀속 (ADR-0002).
    assert body["photo_id"] == "p4"
    assert db.get_note("p4") == "메모"
    assert db.get_note("p5") is None


def test_put_note_embed_failure_keeps_note_and_returns_false(tmp_path: Path):
    client, db, store = _env(tmp_path, DownEmbedClient())
    body = client.put("/api/photos/p1/note", json={"text": "벚꽃"}).json()

    assert body == {"photo_id": "p1", "text": "벚꽃", "embedded": False}
    assert db.get_note("p1") == "벚꽃"  # 저장은 성공 (S5 수용 기준)
    assert store.count() == 0
    # 미임베딩 메모 = embeddings 행 없음 — 추후 재임베딩 식별 계약 (prd §6-b).
    assert db.count_embeddings(kind="note_text") == 0
    with db.connect() as conn:
        stages = [row["stage"] for row in conn.execute("SELECT stage FROM index_errors")]
    assert "note_embed" in stages


def test_photo_detail_includes_note(env):
    client, _, _ = env
    assert client.get("/api/photos/p1").json()["note"] is None
    client.put("/api/photos/p1/note", json={"text": "벚꽃길"})
    assert client.get("/api/photos/p1").json()["note"] == "벚꽃길"
    # duplicate 상세는 canonical을 따른다 — 메모도 canonical(p4) 것이 보인다.
    client.put("/api/photos/p4/note", json={"text": "canonical 메모"})
    assert client.get("/api/photos/p5").json()["note"] == "canonical 메모"


def test_delete_note_removes_row_vector_and_embedding(env):
    client, db, store = env
    client.put("/api/photos/p1/note", json={"text": "지울 메모"})
    assert store.count() == 1

    response = client.delete("/api/photos/p1/note")

    assert response.status_code == 204
    assert db.get_note("p1") is None
    assert store.count() == 0
    assert db.count_embeddings(kind="note_text") == 0
    # 메모가 없으면 404 — 미존재 사진도 동일.
    assert client.delete("/api/photos/p1/note").status_code == 404
    assert client.delete("/api/photos/nope/note").status_code == 404


def test_delete_note_works_for_unembedded_note(tmp_path: Path):
    # embedded:false로 저장된 메모(벡터 없음)도 삭제는 204로 끝난다.
    client, db, _ = _env(tmp_path, DownEmbedClient())
    client.put("/api/photos/p1/note", json={"text": "벚꽃"})
    assert client.delete("/api/photos/p1/note").status_code == 204
    assert db.get_note("p1") is None

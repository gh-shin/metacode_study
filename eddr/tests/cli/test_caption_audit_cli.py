import json
from pathlib import Path
from unittest.mock import MagicMock

from eddr.cli import main
from eddr.db.repository import EddrDatabase, PhotoRecord
from eddr.vector.chroma_store import VectorHit


class FakeEmbeddingClient:
    def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorStore:
    def query(self, embedding, k, where=None):
        return [
            VectorHit(
                id="v:wrong-noodle",
                photo_id="wrong-noodle",
                document="",
                metadata={},
                distance=0.2,
            )
        ]


def test_cli_search_audit_writes_json_report(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "eddr.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()
    db.upsert_photo(
        PhotoRecord(
            id="wrong-noodle",
            source="local",
            source_uri="/photos/wrong-noodle.jpg",
            image_path="/photos/wrong-noodle.jpg",
            indexing_status="caption_done",
        )
    )
    db.upsert_caption(
        "wrong-noodle",
        "gemma4:e2b",
        "en",
        "A soup misdescribed as noodles.\n\nSearch keywords: noodles, soup, food",
    )

    import eddr.vector.chroma_store as chroma_module
    import eddr.vision.ollama_client as ollama_module

    monkeypatch.setattr(chroma_module, "ChromaVectorStore", lambda path: FakeVectorStore())
    monkeypatch.setattr(ollama_module, "OllamaVisionClient", lambda: FakeEmbeddingClient())

    out = tmp_path / "audit.json"
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps(
            {
                "wrong-noodle": {
                    "visual_target": False,
                    "caption_claims_target": True,
                    "review_label": "wrong_object_sprouts_as_noodles",
                }
            }
        ),
        encoding="utf-8",
    )
    rc = main(
        [
            "search",
            "audit",
            "냉면",
            "--db",
            str(db_path),
            "--chroma",
            str(tmp_path / "chroma"),
            "--keyword",
            "cold noodles",
            "--keyword",
            "food",
            "--labels",
            str(labels),
            "--out",
            str(out),
        ]
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["query"] == "냉면"
    assert payload["keywords"] == ["cold noodles", "food"]
    assert payload["keyword_stats"]["food"]["document_count"] == 1
    assert payload["hits"][0]["photo_id"] == "wrong-noodle"
    assert payload["hits"][0]["vector_rank"] == 1
    assert payload["hits"][0]["review_label"] == "wrong_object_sprouts_as_noodles"
    assert payload["hits"][0]["bucket"] == "caption_false_positive"


def _make_photo(photo_id: str, tmp_path: Path) -> PhotoRecord:
    """테스트용 임시 이미지 파일을 만들고 PhotoRecord를 반환한다."""
    img_path = tmp_path / f"{photo_id}.jpg"
    img_path.write_bytes(b"\xff\xd8\xff")  # 최소 JPEG 헤더
    return PhotoRecord(
        id=photo_id,
        source="local",
        source_uri=str(img_path),
        image_path=str(img_path),
        indexing_status="caption_done",
    )


def test_cli_vision_recaption_routes_to_batch_function(tmp_path: Path, monkeypatch):
    """vision recaption이 올바른 doc_photos/nondoc_photos로 배치 함수를 호출하는지 확인."""
    db_path = tmp_path / "eddr.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()

    doc_photo = _make_photo("doc:001", tmp_path)
    nondoc_photo = _make_photo("nondoc:001", tmp_path)
    db.upsert_photo(doc_photo)
    db.upsert_photo(nondoc_photo)

    foodset = {"doc": [{"photo_id": "doc:001"}], "nondoc": [{"photo_id": "nondoc:001"}]}
    foodset_path = tmp_path / "foodset.json"
    foodset_path.write_text(json.dumps(foodset), encoding="utf-8")

    from eddr.vision.batch import VisionBatchReport

    captured_calls = {}

    def fake_routed_dual(
        db_,
        vs,
        embed_client,
        *,
        doc_client,
        nondoc_local_client,
        nondoc_remote_client,
        doc_photos,
        nondoc_photos,
        persist_vector=True,
    ):
        captured_calls["doc_photos"] = [p.id for p in doc_photos]
        captured_calls["nondoc_photos"] = [p.id for p in nondoc_photos]
        captured_calls["embed_client"] = embed_client
        captured_calls["doc_client"] = doc_client
        captured_calls["nondoc_local_client"] = nondoc_local_client
        captured_calls["nondoc_remote_client"] = nondoc_remote_client
        return VisionBatchReport(processed=2, failed=0)

    import eddr.vector.chroma_store as chroma_module
    import eddr.vision.batch as batch_module
    import eddr.vision.ollama_client as ollama_module

    monkeypatch.setattr(batch_module, "run_caption_text_batch_routed_dual", fake_routed_dual)
    monkeypatch.setattr(chroma_module, "ChromaVectorStore", lambda path: MagicMock())
    fake_client = MagicMock()
    fake_client.caption_model = "qwen3-vl:8b"
    monkeypatch.setattr(ollama_module, "OllamaVisionClient", lambda **kw: fake_client)

    rc = main(
        [
            "vision",
            "recaption",
            "--photo-set",
            str(foodset_path),
            "--db",
            str(db_path),
            "--chroma",
            str(tmp_path / "chroma"),
            "--limit",
            "1",
        ]
    )

    assert rc == 0
    assert captured_calls["doc_photos"] == ["doc:001"]
    assert captured_calls["nondoc_photos"] == ["nondoc:001"]
    # remote_host 없으면 nondoc_remote_client == nondoc_local_client
    assert captured_calls["nondoc_remote_client"] is captured_calls["nondoc_local_client"]


def test_cli_vision_recaption_skips_missing_photo_id(tmp_path: Path, monkeypatch, capsys):
    """DB에 없는 photo_id는 경고를 출력하고 skip한다."""
    db_path = tmp_path / "eddr.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()

    foodset = {"doc": [{"photo_id": "missing:999"}], "nondoc": []}
    foodset_path = tmp_path / "foodset.json"
    foodset_path.write_text(json.dumps(foodset), encoding="utf-8")

    from eddr.vision.batch import VisionBatchReport

    captured_calls = {}

    def fake_routed_dual(
        db_,
        vs,
        embed_client,
        *,
        doc_client,
        nondoc_local_client,
        nondoc_remote_client,
        doc_photos,
        nondoc_photos,
        persist_vector=True,
    ):
        captured_calls["doc_photos"] = doc_photos
        captured_calls["nondoc_photos"] = nondoc_photos
        return VisionBatchReport(processed=0, failed=0)

    import eddr.vector.chroma_store as chroma_module
    import eddr.vision.batch as batch_module
    import eddr.vision.ollama_client as ollama_module

    monkeypatch.setattr(batch_module, "run_caption_text_batch_routed_dual", fake_routed_dual)
    monkeypatch.setattr(chroma_module, "ChromaVectorStore", lambda path: MagicMock())
    monkeypatch.setattr(ollama_module, "OllamaVisionClient", lambda **kw: MagicMock())

    rc = main(
        [
            "vision",
            "recaption",
            "--photo-set",
            str(foodset_path),
            "--db",
            str(db_path),
            "--chroma",
            str(tmp_path / "chroma"),
        ]
    )

    assert rc == 0
    assert captured_calls["doc_photos"] == []
    out = capsys.readouterr().out
    assert "missing:999" in out


# ── --no-vector 플래그 및 reindex-vectors 테스트 ──────────────────────────────


def test_cli_vision_recaption_no_vector_passes_persist_vector_false(tmp_path: Path, monkeypatch):
    """--no-vector 플래그 지정 시 persist_vector=False가 전달된다."""
    db_path = tmp_path / "eddr.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()

    doc_photo = _make_photo("doc:001", tmp_path)
    db.upsert_photo(doc_photo)

    foodset = {"doc": [{"photo_id": "doc:001"}], "nondoc": []}
    foodset_path = tmp_path / "foodset.json"
    foodset_path.write_text(json.dumps(foodset), encoding="utf-8")

    from eddr.vision.batch import VisionBatchReport

    captured_kwargs = {}

    def fake_routed_dual(
        db_,
        vs,
        embed_client,
        *,
        doc_client,
        nondoc_local_client,
        nondoc_remote_client,
        doc_photos,
        nondoc_photos,
        persist_vector=True,
    ):
        captured_kwargs["persist_vector"] = persist_vector
        return VisionBatchReport(processed=1, failed=0)

    import eddr.vector.chroma_store as chroma_module
    import eddr.vision.batch as batch_module
    import eddr.vision.ollama_client as ollama_module

    monkeypatch.setattr(batch_module, "run_caption_text_batch_routed_dual", fake_routed_dual)
    monkeypatch.setattr(chroma_module, "ChromaVectorStore", lambda path: MagicMock())
    monkeypatch.setattr(ollama_module, "OllamaVisionClient", lambda **kw: MagicMock())

    rc = main(
        [
            "vision",
            "recaption",
            "--photo-set",
            str(foodset_path),
            "--db",
            str(db_path),
            "--chroma",
            str(tmp_path / "chroma"),
            "--no-vector",
        ]
    )

    assert rc == 0
    assert captured_kwargs["persist_vector"] is False


def test_cli_vision_recaption_default_no_flag_passes_persist_vector_true(
    tmp_path: Path, monkeypatch
):
    """--no-vector 없을 때 persist_vector=True(기본값)가 전달된다."""
    db_path = tmp_path / "eddr.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()

    foodset = {"doc": [], "nondoc": []}
    foodset_path = tmp_path / "foodset.json"
    foodset_path.write_text(json.dumps(foodset), encoding="utf-8")

    from eddr.vision.batch import VisionBatchReport

    captured_kwargs = {}

    def fake_routed_dual(
        db_,
        vs,
        embed_client,
        *,
        doc_client,
        nondoc_local_client,
        nondoc_remote_client,
        doc_photos,
        nondoc_photos,
        persist_vector=True,
    ):
        captured_kwargs["persist_vector"] = persist_vector
        return VisionBatchReport(processed=0, failed=0)

    import eddr.vector.chroma_store as chroma_module
    import eddr.vision.batch as batch_module
    import eddr.vision.ollama_client as ollama_module

    monkeypatch.setattr(batch_module, "run_caption_text_batch_routed_dual", fake_routed_dual)
    monkeypatch.setattr(chroma_module, "ChromaVectorStore", lambda path: MagicMock())
    monkeypatch.setattr(ollama_module, "OllamaVisionClient", lambda **kw: MagicMock())

    rc = main(
        [
            "vision",
            "recaption",
            "--photo-set",
            str(foodset_path),
            "--db",
            str(db_path),
            "--chroma",
            str(tmp_path / "chroma"),
        ]
    )

    assert rc == 0
    assert captured_kwargs["persist_vector"] is True


def test_cli_vision_reindex_vectors_embeds_and_upserts_per_photo(tmp_path: Path, monkeypatch):
    """reindex-vectors가 photo_id별 embed·upsert·record를 순차 실행한다."""
    db_path = tmp_path / "eddr.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()

    # 캡션이 있는 사진 2장, 없는 사진 1장
    for pid in ("p1", "p2", "p3"):
        db.upsert_photo(
            PhotoRecord(
                id=pid,
                source="local",
                source_uri=f"/{pid}.jpg",
                image_path=f"/{pid}.jpg",
                indexing_status="caption_done",
            )
        )
    db.upsert_caption("p1", "fake-model", "en", "caption one")
    db.upsert_caption("p2", "fake-model", "en", "caption two")
    # p3는 캡션 없음 → skip

    photo_set = {"doc": [{"photo_id": "p1"}, {"photo_id": "p3"}], "nondoc": [{"photo_id": "p2"}]}
    photo_set_path = tmp_path / "foodset.json"
    photo_set_path.write_text(json.dumps(photo_set), encoding="utf-8")

    embed_calls: list[str] = []
    upsert_calls: list[str] = []

    class FakeEmbedClient:
        embedding_model = "fake-emb"

        def embed_texts(self, texts):
            embed_calls.extend(texts)
            return [[0.1, 0.2, 0.3] for _ in texts]

    class FakeVS:
        def upsert(self, ids, embeddings, documents, metadatas):
            upsert_calls.extend(ids)

    import eddr.vector.chroma_store as chroma_module
    import eddr.vision.ollama_client as ollama_module

    monkeypatch.setattr(chroma_module, "ChromaVectorStore", lambda path: FakeVS())
    monkeypatch.setattr(ollama_module, "OllamaVisionClient", lambda **kw: FakeEmbedClient())

    rc = main(
        [
            "vision",
            "reindex-vectors",
            "--photo-set",
            str(photo_set_path),
            "--db",
            str(db_path),
            "--chroma",
            str(tmp_path / "chroma"),
        ]
    )

    assert rc == 0
    # p1·p2만 캡션 있어서 embed·upsert 호출됨, p3은 skip
    assert len(embed_calls) == 2
    assert len(upsert_calls) == 2
    # embedding record도 DB에 기록됨
    assert db.count_embeddings(kind="caption_text") == 2


def test_cli_vision_reindex_vectors_skips_no_caption(tmp_path: Path, monkeypatch):
    """캡션 없는 photo_id는 조용히 skip한다."""
    db_path = tmp_path / "eddr.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()

    db.upsert_photo(
        PhotoRecord(
            id="no-caption",
            source="local",
            source_uri="/x.jpg",
            image_path="/x.jpg",
        )
    )

    photo_set = {"doc": [{"photo_id": "no-caption"}], "nondoc": []}
    photo_set_path = tmp_path / "ps.json"
    photo_set_path.write_text(json.dumps(photo_set), encoding="utf-8")

    embed_calls: list = []

    class FakeEmbedClient:
        embedding_model = "fake-emb"

        def embed_texts(self, texts):
            embed_calls.extend(texts)
            return [[0.1] for _ in texts]

    import eddr.vector.chroma_store as chroma_module
    import eddr.vision.ollama_client as ollama_module

    monkeypatch.setattr(chroma_module, "ChromaVectorStore", lambda path: MagicMock())
    monkeypatch.setattr(ollama_module, "OllamaVisionClient", lambda **kw: FakeEmbedClient())

    rc = main(
        [
            "vision",
            "reindex-vectors",
            "--photo-set",
            str(photo_set_path),
            "--db",
            str(db_path),
            "--chroma",
            str(tmp_path / "chroma"),
        ]
    )

    assert rc == 0
    assert embed_calls == []

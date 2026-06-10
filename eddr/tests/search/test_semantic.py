from pathlib import Path

from eddr.db.repository import EddrDatabase, PhotoRecord
from eddr.search.semantic import semantic_search
from eddr.vector.memory_store import MemoryVectorStore


class FakeEmbeddingClient:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        assert texts == ["해변 불빛"]
        return [[1.0, 0.0, 0.0]]


def test_semantic_search_embeds_query_and_joins_photo_metadata(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.upsert_photo(
        PhotoRecord(
            id="local:beach",
            source="local",
            source_uri="/photos/beach.jpg",
            image_path="/photos/beach.jpg",
            content_hash="beach",
            taken_at="2020-06-20T10:00:00+00:00",
            indexing_status="caption_done",
        )
    )
    db.upsert_caption("local:beach", "gemma4:e2b", "en", "A night beach with light trails.")

    store = MemoryVectorStore()
    store.upsert(
        ids=["caption_text:local:beach:qwen3-embedding:8b"],
        embeddings=[[1.0, 0.0, 0.0]],
        documents=["A night beach with light trails."],
        metadatas=[{"photo_id": "local:beach", "source": "local", "kind": "caption_text"}],
    )

    results = semantic_search(
        query="해변 불빛",
        db=db,
        vector_store=store,
        embedding_client=FakeEmbeddingClient(),
        k=5,
    )

    assert len(results) == 1
    assert results[0].photo_id == "local:beach"
    assert results[0].image_path == "/photos/beach.jpg"
    assert results[0].caption == "A night beach with light trails."

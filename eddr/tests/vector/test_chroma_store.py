from pathlib import Path

import pytest

from eddr.vector.chroma_store import ChromaVectorStore


def test_chroma_store_upserts_and_queries_with_metadata_filter(tmp_path: Path):
    store = ChromaVectorStore(path=tmp_path / "chroma", collection_name="test_caption_text")

    store.upsert(
        ids=["v1", "v2"],
        embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        documents=["beach light trail", "wedding table"],
        metadatas=[
            {"photo_id": "p1", "source": "local", "kind": "caption_text"},
            {"photo_id": "p2", "source": "google_takeout", "kind": "caption_text"},
        ],
    )

    assert store.count() == 2
    result = store.query(
        embedding=[1.0, 0.0, 0.0],
        k=2,
        where={"source": "local"},
    )

    assert [hit.photo_id for hit in result] == ["p1"]
    assert result[0].document == "beach light trail"


def test_chroma_store_rejects_mismatched_batch_lengths(tmp_path: Path):
    store = ChromaVectorStore(path=tmp_path / "chroma", collection_name="test_caption_text")

    with pytest.raises(ValueError, match="same length"):
        store.upsert(
            ids=["v1"],
            embeddings=[[1.0, 0.0, 0.0]],
            documents=["one", "two"],
            metadatas=[{"photo_id": "p1"}],
        )

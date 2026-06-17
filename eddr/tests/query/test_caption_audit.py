from pathlib import Path

from eddr.db.repository import EddrDatabase, PhotoRecord
from eddr.query.audit import CaptionAuditLabel, trace_caption_search
from eddr.vector.chroma_store import VectorHit


class FakeEmbeddingClient:
    def embed_texts(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorStore:
    def __init__(self, ordered_ids):
        self.ordered_ids = ordered_ids
        self.last_k = None
        self.requested = []

    def query(self, embedding, k, where=None):
        self.last_k = k
        self.requested.append(k)
        return [
            VectorHit(
                id=f"v:{photo_id}",
                photo_id=photo_id,
                document="",
                metadata={},
                distance=0.2 + 0.01 * index,
            )
            for index, photo_id in enumerate(self.ordered_ids[:k])
        ]


def make_audit_db(tmp_path: Path) -> EddrDatabase:
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    for photo_id, caption in {
        "wrong-noodle": (
            "A close-up of soup with pale strands described as noodles.\n\n"
            "Search keywords: noodles, soup, Asian food, food"
        ),
        "real-naengmyeon": (
            "A bowl of cold noodles with broth and garnish.\n\n"
            "Search keywords: cold noodles, naengmyeon, Korean food, food"
        ),
        "sprouts": (
            "A bowl topped with bean sprouts and vegetables.\n\n"
            "Search keywords: bean sprouts, vegetables, soup, food"
        ),
    }.items():
        db.upsert_photo(
            PhotoRecord(
                id=photo_id,
                source="local",
                source_uri=f"/photos/{photo_id}.jpg",
                image_path=f"/photos/{photo_id}.jpg",
                indexing_status="caption_done",
            )
        )
        db.upsert_caption(photo_id, "gemma4:e2b", "en", caption)
    return db


def test_trace_caption_search_separates_caption_error_from_retrieval_noise(tmp_path: Path):
    db = make_audit_db(tmp_path)
    store = FakeVectorStore(["wrong-noodle", "real-naengmyeon", "sprouts"])
    labels = {
        "wrong-noodle": CaptionAuditLabel(
            visual_target=False,
            caption_claims_target=True,
            review_label="wrong_object_sprouts_as_noodles",
        ),
        "real-naengmyeon": CaptionAuditLabel(visual_target=True, caption_claims_target=True),
        "sprouts": CaptionAuditLabel(visual_target=False, caption_claims_target=False),
    }

    report = trace_caption_search(
        db=db,
        vector_store=store,
        embedding_client=FakeEmbeddingClient(),
        query="냉면",
        keywords=["cold noodles", "food"],
        k=3,
        labels=labels,
    )

    wrong = next(hit for hit in report.hits if hit.photo_id == "wrong-noodle")
    assert wrong.vector_rank == 1
    assert wrong.lexical_rank is not None
    assert wrong.matched_keywords == ("food",)
    assert wrong.review_label == "wrong_object_sprouts_as_noodles"
    assert wrong.bucket == "caption_false_positive"

    real = next(hit for hit in report.hits if hit.photo_id == "real-naengmyeon")
    assert real.matched_keywords == ("cold noodles", "food")
    assert real.bucket == "aligned_positive"

    sprouts = next(hit for hit in report.hits if hit.photo_id == "sprouts")
    assert sprouts.bucket == "retrieval_noise"

    assert report.keyword_stats["cold noodles"].document_count == 1
    assert report.keyword_stats["food"].document_count == 3
    assert store.last_k == 15


def test_trace_caption_search_expands_vector_pool_after_filtering(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.upsert_photo(
        PhotoRecord(
            id="real",
            source="local",
            source_uri="/photos/real.jpg",
            image_path="/photos/real.jpg",
            indexing_status="caption_done",
        )
    )
    db.upsert_caption("real", "gemma4:e2b", "en", "A valid caption.\n\nSearch keywords: food")
    store = FakeVectorStore(
        ["missing-1", "missing-2", "missing-3", "missing-4", "missing-5", "real"]
    )

    report = trace_caption_search(
        db=db,
        vector_store=store,
        embedding_client=FakeEmbeddingClient(),
        query="냉면",
        k=1,
    )

    assert store.requested == [5, 25]
    assert [hit.photo_id for hit in report.hits] == ["real"]

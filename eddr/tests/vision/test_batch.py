import threading
import time
from pathlib import Path

from eddr.db.repository import EddrDatabase, PhotoRecord
from eddr.vector.memory_store import MemoryVectorStore
from eddr.vision.batch import (
    _persist_caption,
    run_caption_text_batch,
    run_caption_text_batch_dual,
    run_caption_text_batch_routed_dual,
)


class FakeVisionClient:
    caption_model = "fake-caption"
    embedding_model = "fake-embedding"

    def __init__(self):
        self.captioned_photos: list[PhotoRecord] = []

    def caption_photo(self, photo: PhotoRecord) -> str:
        self.captioned_photos.append(photo)
        return f"caption for {Path(photo.image_path or '').name}"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0, 0.0] for text in texts]


def test_run_caption_text_batch_skips_completed_rows(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    first = tmp_path / "first.jpg"
    first.write_bytes(b"first")
    second = tmp_path / "second.jpg"
    second.write_bytes(b"second")

    db.upsert_photo(
        PhotoRecord(
            id="local:first",
            source="local",
            source_uri=str(first),
            image_path=str(first),
            content_hash="first",
            width=640,
            height=480,
            indexing_status="caption_done",
        )
    )
    db.upsert_caption("local:first", "fake-caption", "en", "existing")

    db.upsert_photo(
        PhotoRecord(
            id="local:second",
            source="local",
            source_uri=str(second),
            image_path=str(second),
            content_hash="second",
            width=640,
            height=480,
            indexing_status="meta_done",
        )
    )

    vision_client = FakeVisionClient()
    report = run_caption_text_batch(
        db=db,
        vector_store=MemoryVectorStore(),
        vision_client=vision_client,
        limit=10,
    )

    assert report.processed == 1
    assert report.failed == 0
    assert [photo.id for photo in vision_client.captioned_photos] == ["local:second"]
    assert db.get_photo("local:second").indexing_status == "caption_done"
    assert db.count_captions() == 2
    assert db.count_embeddings(kind="caption_text") == 1


class _ConcurrencyTracker:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def enter(self):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    def leave(self):
        with self._lock:
            self.active -= 1


class TrackingCaptionClient:
    caption_model = "fake-caption"
    embedding_model = "fake-embedding"

    def __init__(self, tracker: _ConcurrencyTracker):
        self.tracker = tracker
        self.captioned: list[str] = []
        self.embed_calls = 0
        self._lock = threading.Lock()

    def caption_photo(self, photo: PhotoRecord) -> str:
        self.tracker.enter()
        time.sleep(0.05)
        with self._lock:
            self.captioned.append(photo.id)
        self.tracker.leave()
        return f"caption for {photo.id}"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            self.embed_calls += 1
        return [[float(len(text)), 1.0, 0.0] for text in texts]


def _make_meta_done_photos(db: EddrDatabase, tmp_path: Path, n: int) -> None:
    for i in range(n):
        image = tmp_path / f"{i}.jpg"
        image.write_bytes(b"x")
        db.upsert_photo(
            PhotoRecord(
                id=f"local:{i}",
                source="local",
                source_uri=str(image),
                image_path=str(image),
                content_hash=f"h{i}",
                indexing_status="meta_done",
            )
        )


def test_dual_batch_persists_all_photos_and_embeds_locally(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    _make_meta_done_photos(db, tmp_path, 4)
    tracker = _ConcurrencyTracker()
    local = TrackingCaptionClient(tracker)
    remote = TrackingCaptionClient(tracker)

    report = run_caption_text_batch_dual(
        db=db,
        vector_store=MemoryVectorStore(),
        local_client=local,
        remote_client=remote,
        limit=10,
    )

    assert report.processed == 4
    assert report.failed == 0
    # every photo captioned exactly once, distributed across the two clients
    assert sorted(local.captioned + remote.captioned) == [
        "local:0",
        "local:1",
        "local:2",
        "local:3",
    ]
    # embeddings flow only through the local client (vector-space consistency)
    assert remote.embed_calls == 0
    assert local.embed_calls == 4
    assert db.count_captions() == 4
    assert db.count_embeddings(kind="caption_text") == 4
    for i in range(4):
        assert db.get_photo(f"local:{i}").indexing_status == "caption_done"


def test_dual_batch_runs_captions_concurrently(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    _make_meta_done_photos(db, tmp_path, 6)
    tracker = _ConcurrencyTracker()
    local = TrackingCaptionClient(tracker)
    remote = TrackingCaptionClient(tracker)

    report = run_caption_text_batch_dual(
        db=db,
        vector_store=MemoryVectorStore(),
        local_client=local,
        remote_client=remote,
        limit=10,
    )

    assert report.processed == 6
    assert tracker.max_active == 2  # both caption clients ran at the same time


class RoutingCaptionClient:
    """caption_model을 태그하고 자신이 캡션한 photo_id를 기록하는 fake client."""

    embedding_model = "fake-embedding"

    def __init__(self, caption_model: str):
        self.caption_model = caption_model
        self.captioned: list[str] = []
        self.embed_calls = 0
        self._lock = threading.Lock()

    def caption_photo(self, photo: PhotoRecord) -> str:
        time.sleep(0.01)
        with self._lock:
            self.captioned.append(photo.id)
        return f"{self.caption_model} caption for {photo.id}"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            self.embed_calls += 1
        return [[float(len(text)), 1.0, 0.0] for text in texts]


def _photo_caption_model(db: EddrDatabase, photo_id: str) -> str:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT model_id FROM captions WHERE photo_id = ?",
            (photo_id,),
        ).fetchone()
    return str(row["model_id"])


def _make_photos(db: EddrDatabase, tmp_path: Path, ids: list[str]) -> list[PhotoRecord]:
    photos: list[PhotoRecord] = []
    for pid in ids:
        image = tmp_path / f"{pid}.jpg"
        image.write_bytes(b"x")
        record = PhotoRecord(
            id=f"local:{pid}",
            source="local",
            source_uri=str(image),
            image_path=str(image),
            content_hash=f"h{pid}",
            indexing_status="meta_done",
        )
        db.upsert_photo(record)
        photos.append(db.get_photo(f"local:{pid}"))
    return photos


def test_routed_dual_routes_doc_to_doc_client_and_nondoc_to_gemma(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    doc_photos = _make_photos(db, tmp_path, ["doc0", "doc1"])
    nondoc_photos = _make_photos(db, tmp_path, ["food0", "food1", "food2"])

    doc_client = RoutingCaptionClient("qwen-fake")
    nondoc_local = RoutingCaptionClient("gemma-fake")
    nondoc_remote = RoutingCaptionClient("gemma-fake")
    vector_store = MemoryVectorStore()

    report = run_caption_text_batch_routed_dual(
        db=db,
        vector_store=vector_store,
        embed_client=doc_client,
        doc_client=doc_client,
        nondoc_local_client=nondoc_local,
        nondoc_remote_client=nondoc_remote,
        doc_photos=doc_photos,
        nondoc_photos=nondoc_photos,
    )

    assert report.processed == 5
    assert report.failed == 0

    # 문서 사진은 오직 doc_client(qwen)가 캡션
    assert sorted(doc_client.captioned) == ["local:doc0", "local:doc1"]
    # 비문서 사진은 두 gemma client가 나눠서 캡션, doc_client는 비문서를 안 건드림
    assert sorted(nondoc_local.captioned + nondoc_remote.captioned) == [
        "local:food0",
        "local:food1",
        "local:food2",
    ]
    for pid in ("local:food0", "local:food1", "local:food2"):
        assert pid not in doc_client.captioned

    # DB model_id가 실제 캡션한 모델로 기록됨
    assert _photo_caption_model(db, "local:doc0") == "qwen-fake"
    assert _photo_caption_model(db, "local:doc1") == "qwen-fake"
    for pid in ("local:food0", "local:food1", "local:food2"):
        assert _photo_caption_model(db, pid) == "gemma-fake"

    # 5장 모두 persist: DB caption·embedding·status, Chroma upsert
    assert db.count_captions() == 5
    assert db.count_embeddings(kind="caption_text") == 5
    assert vector_store.count() == 5
    for pid in ("doc0", "doc1", "food0", "food1", "food2"):
        assert db.get_photo(f"local:{pid}").indexing_status == "caption_done"


def test_routed_dual_local_switches_to_nondoc_after_doc_drained(tmp_path: Path):
    # 문서 1장 + 비문서 5장 → 로컬이 문서 비운 뒤 비문서로 전환해 함께 처리
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    doc_photos = _make_photos(db, tmp_path, ["doc0"])
    nondoc_photos = _make_photos(db, tmp_path, [f"food{i}" for i in range(5)])

    doc_client = RoutingCaptionClient("qwen-fake")
    nondoc_local = RoutingCaptionClient("gemma-fake")
    nondoc_remote = RoutingCaptionClient("gemma-fake")

    report = run_caption_text_batch_routed_dual(
        db=db,
        vector_store=MemoryVectorStore(),
        embed_client=doc_client,
        doc_client=doc_client,
        nondoc_local_client=nondoc_local,
        nondoc_remote_client=nondoc_remote,
        doc_photos=doc_photos,
        nondoc_photos=nondoc_photos,
    )

    assert report.processed == 6
    assert report.failed == 0
    assert doc_client.captioned == ["local:doc0"]
    # 로컬이 문서 소진 후 비문서로 전환 → 로컬도 비문서를 일부 처리(원격과 함께)
    assert nondoc_local.captioned, "로컬 client가 문서 소진 후 비문서 큐로 전환해야 함"
    assert sorted(nondoc_local.captioned + nondoc_remote.captioned) == [
        f"local:food{i}" for i in range(5)
    ]


def test_routed_dual_empty_nondoc_only_doc(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    doc_photos = _make_photos(db, tmp_path, ["doc0", "doc1"])

    doc_client = RoutingCaptionClient("qwen-fake")
    nondoc_local = RoutingCaptionClient("gemma-fake")
    nondoc_remote = RoutingCaptionClient("gemma-fake")

    report = run_caption_text_batch_routed_dual(
        db=db,
        vector_store=MemoryVectorStore(),
        embed_client=doc_client,
        doc_client=doc_client,
        nondoc_local_client=nondoc_local,
        nondoc_remote_client=nondoc_remote,
        doc_photos=doc_photos,
        nondoc_photos=[],
    )

    assert report.processed == 2
    assert report.failed == 0
    assert sorted(doc_client.captioned) == ["local:doc0", "local:doc1"]
    assert nondoc_local.captioned == []
    assert nondoc_remote.captioned == []
    assert db.count_captions() == 2


def test_routed_dual_empty_doc_only_nondoc(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    nondoc_photos = _make_photos(db, tmp_path, ["food0", "food1", "food2"])

    doc_client = RoutingCaptionClient("qwen-fake")
    nondoc_local = RoutingCaptionClient("gemma-fake")
    nondoc_remote = RoutingCaptionClient("gemma-fake")

    report = run_caption_text_batch_routed_dual(
        db=db,
        vector_store=MemoryVectorStore(),
        embed_client=nondoc_local,
        doc_client=doc_client,
        nondoc_local_client=nondoc_local,
        nondoc_remote_client=nondoc_remote,
        doc_photos=[],
        nondoc_photos=nondoc_photos,
    )

    assert report.processed == 3
    assert report.failed == 0
    assert doc_client.captioned == []
    assert sorted(nondoc_local.captioned + nondoc_remote.captioned) == [
        "local:food0",
        "local:food1",
        "local:food2",
    ]
    for pid in ("local:food0", "local:food1", "local:food2"):
        assert _photo_caption_model(db, pid) == "gemma-fake"


# ── persist_vector=False 분기 테스트 ──────────────────────────────────────────


class _TrackingVectorStore:
    """upsert 호출 횟수를 추적하는 fake 벡터 스토어."""

    def __init__(self):
        self.upsert_calls = 0

    def upsert(self, ids, embeddings, documents, metadatas):
        self.upsert_calls += 1


class _TrackingEmbedClient:
    """embed_texts 호출 횟수를 추적하는 fake embed 클라이언트."""

    caption_model = "fake-caption"
    embedding_model = "fake-embedding"

    def __init__(self):
        self.embed_calls = 0

    def embed_texts(self, texts):
        self.embed_calls += 1
        return [[0.1, 0.2, 0.3] for _ in texts]


def test_persist_caption_no_vector_skips_embed_and_chroma(tmp_path: Path):
    """persist_vector=False이면 embed_texts·vector_store.upsert를 호출하지 않는다."""
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    photo = PhotoRecord(
        id="local:a",
        source="local",
        source_uri=str(img),
        image_path=str(img),
        indexing_status="meta_done",
    )
    db.upsert_photo(photo)

    vector_store = _TrackingVectorStore()
    embed_client = _TrackingEmbedClient()

    _persist_caption(
        db,
        vector_store,
        photo=photo,
        caption="a cat on a table",
        caption_model="fake-caption",
        embed_client=embed_client,
        persist_vector=False,
    )

    assert embed_client.embed_calls == 0
    assert vector_store.upsert_calls == 0
    assert db.count_captions() == 1
    assert db.get_photo("local:a").indexing_status == "caption_done"
    assert db.count_embeddings(kind="caption_text") == 0


def test_persist_caption_default_true_calls_embed_and_chroma(tmp_path: Path):
    """persist_vector 기본값(True)이면 기존 동작을 유지한다."""
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    img = tmp_path / "b.jpg"
    img.write_bytes(b"x")
    photo = PhotoRecord(
        id="local:b",
        source="local",
        source_uri=str(img),
        image_path=str(img),
        indexing_status="meta_done",
    )
    db.upsert_photo(photo)

    vector_store = _TrackingVectorStore()
    embed_client = _TrackingEmbedClient()

    _persist_caption(
        db,
        vector_store,
        photo=photo,
        caption="a dog on a sofa",
        caption_model="fake-caption",
        embed_client=embed_client,
    )

    assert embed_client.embed_calls == 1
    assert vector_store.upsert_calls == 1
    assert db.count_captions() == 1
    assert db.count_embeddings(kind="caption_text") == 1


def test_routed_dual_no_vector_skips_chroma(tmp_path: Path):
    """persist_vector=False이면 run_caption_text_batch_routed_dual이 Chroma를 건드리지 않는다."""
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    doc_photos = _make_photos(db, tmp_path, ["doc0"])
    nondoc_photos = _make_photos(db, tmp_path, ["food0"])

    doc_client = RoutingCaptionClient("qwen-fake")
    nondoc_local = RoutingCaptionClient("gemma-fake")
    nondoc_remote = RoutingCaptionClient("gemma-fake")
    vector_store = _TrackingVectorStore()

    report = run_caption_text_batch_routed_dual(
        db=db,
        vector_store=vector_store,
        embed_client=doc_client,
        doc_client=doc_client,
        nondoc_local_client=nondoc_local,
        nondoc_remote_client=nondoc_remote,
        doc_photos=doc_photos,
        nondoc_photos=nondoc_photos,
        persist_vector=False,
    )

    assert report.processed == 2
    assert report.failed == 0
    assert vector_store.upsert_calls == 0
    assert db.count_captions() == 2
    assert db.count_embeddings(kind="caption_text") == 0

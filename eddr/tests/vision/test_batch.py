import threading
import time
from pathlib import Path

from eddr.db.repository import EddrDatabase, PhotoRecord
from eddr.vector.memory_store import MemoryVectorStore
from eddr.vision.batch import run_caption_text_batch, run_caption_text_batch_dual


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

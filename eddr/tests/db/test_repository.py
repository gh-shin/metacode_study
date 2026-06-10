from pathlib import Path

import pytest

from eddr.db.repository import EddrDatabase, PhotoRecord


def test_photo_caption_and_vector_state_round_trip(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    db.upsert_photo(
        PhotoRecord(
            id="local:abc",
            source="local",
            source_uri="/photos/a.jpg",
            image_path="/photos/a.jpg",
            content_hash="abc",
            perceptual_hash="ff00",
            taken_at="2020-06-20T10:00:00+00:00",
            latitude=37.1,
            longitude=127.2,
            width=1200,
            height=800,
            indexing_status="meta_done",
        )
    )

    assert db.count_photos() == 1
    assert [p.id for p in db.pending_vision_photos(limit=10)] == ["local:abc"]

    db.upsert_caption(
        photo_id="local:abc",
        model_id="gemma4:e2b",
        lang="en",
        text="A night beach scene with vehicle light trails.",
    )
    db.upsert_embedding_record(
        photo_id="local:abc",
        kind="caption_text",
        model_id="qwen3-embedding:8b",
        vector_id="caption_text:local:abc:qwen3-embedding:8b",
        dimensions=4096,
    )
    db.update_status("local:abc", "caption_done")

    row = db.get_photo("local:abc")
    assert row is not None
    assert row.indexing_status == "caption_done"
    assert db.pending_vision_photos(limit=10) == []
    assert db.count_captions() == 1
    assert db.count_embeddings(kind="caption_text") == 1


def test_pending_vision_photos_excludes_skipped_video(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    db.upsert_photo(
        PhotoRecord(
            id="local:img",
            source="local",
            source_uri="/photos/a.jpg",
            image_path="/photos/a.jpg",
            indexing_status="meta_done",
        )
    )
    db.upsert_photo(
        PhotoRecord(
            id="local:vid",
            source="local",
            source_uri="/photos/clip.mov",
            image_path="/photos/clip.mov",
            indexing_status="skipped_video",
        )
    )

    assert [p.id for p in db.pending_vision_photos(limit=10)] == ["local:img"]


def test_upsert_photo_meta_reload_keeps_caption_done(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    record = PhotoRecord(
        id="local:abc",
        source="local",
        source_uri="/photos/a.jpg",
        image_path="/photos/a.jpg",
        indexing_status="meta_done",
    )
    db.upsert_photo(record)
    db.update_status("local:abc", "caption_done")

    db.upsert_photo(record)

    assert db.get_photo("local:abc").indexing_status == "caption_done"
    assert db.pending_vision_photos(limit=10) == []


@pytest.mark.parametrize(
    ("existing", "incoming", "expected"),
    [
        ("skipped_video", "meta_done", "skipped_video"),
        ("trip_assigned", "meta_done", "trip_assigned"),
        ("caption_done", "missing_image", "caption_done"),
        ("missing_image", "meta_done", "meta_done"),
        ("meta_done", "missing_image", "missing_image"),
    ],
)
def test_upsert_photo_status_on_reload(tmp_path: Path, existing: str, incoming: str, expected: str):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    db.upsert_photo(
        PhotoRecord(
            id="local:abc",
            source="local",
            source_uri="/photos/a.jpg",
            indexing_status="meta_done",
        )
    )
    db.update_status("local:abc", existing)

    db.upsert_photo(
        PhotoRecord(
            id="local:abc",
            source="local",
            source_uri="/photos/a.jpg",
            indexing_status=incoming,
        )
    )

    assert db.get_photo("local:abc").indexing_status == expected


def test_upsert_photo_preserves_existing_caption(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    record = PhotoRecord(
        id="takeout:def",
        source="google_takeout",
        source_uri="2011/photo.jpg",
        image_path="/staged/def.jpg",
        content_hash="def",
        taken_at="2011-04-02T15:14:20+00:00",
        width=640,
        height=480,
        indexing_status="meta_done",
    )
    db.upsert_photo(record)
    db.upsert_caption("takeout:def", "gemma4:e2b", "en", "first caption")

    db.upsert_photo(
        PhotoRecord(
            **{
                **record.__dict__,
                "width": 800,
                "height": 600,
                "indexing_status": "caption_done",
            }
        )
    )

    assert db.get_photo("takeout:def").width == 800
    assert db.count_captions() == 1

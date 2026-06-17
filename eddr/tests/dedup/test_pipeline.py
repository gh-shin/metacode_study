from pathlib import Path

import numpy as np
from PIL import Image

from eddr.db.repository import EddrDatabase, PhotoRecord
from eddr.dedup.pipeline import backfill_hashes, mark_cross_source_duplicates


def _make_db(tmp_path: Path) -> EddrDatabase:
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    return db


def _save_png(path: Path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    Image.fromarray(rng.integers(0, 255, (32, 32), dtype="uint8"), mode="L").save(path)


def _photo(photo_id: str, source: str, **kwargs) -> PhotoRecord:
    return PhotoRecord(id=photo_id, source=source, source_uri=photo_id, **kwargs)


def test_backfill_fills_both_hashes_for_photos_library(tmp_path: Path):
    db = _make_db(tmp_path)
    img = tmp_path / "a.png"
    _save_png(img, seed=1)
    db.upsert_photo(_photo("photos_library:u1", "photos_library", image_path=str(img)))

    report = backfill_hashes(db)

    assert report.processed == 1
    assert report.errors == 0
    row = db.get_photo("photos_library:u1")
    assert row.content_hash is not None and len(row.content_hash) == 64
    assert row.perceptual_hash is not None and len(row.perceptual_hash) == 16


def test_backfill_fills_only_missing_hash(tmp_path: Path):
    db = _make_db(tmp_path)
    img = tmp_path / "b.png"
    _save_png(img, seed=2)
    db.upsert_photo(
        _photo("google_takeout:keep", "google_takeout", image_path=str(img), content_hash="keep")
    )

    report = backfill_hashes(db)

    assert report.processed == 1
    row = db.get_photo("google_takeout:keep")
    assert row.content_hash == "keep"
    assert row.perceptual_hash is not None


def test_backfill_skips_video_and_complete_rows(tmp_path: Path):
    db = _make_db(tmp_path)
    img = tmp_path / "c.png"
    _save_png(img, seed=3)
    db.upsert_photo(
        _photo(
            "photos_library:vid",
            "photos_library",
            image_path=str(img),
            indexing_status="skipped_video",
        )
    )
    db.upsert_photo(
        _photo(
            "local:done",
            "local",
            image_path=str(img),
            content_hash="ch",
            perceptual_hash="ph",
        )
    )

    report = backfill_hashes(db)

    assert report.processed == 0
    assert db.get_photo("photos_library:vid").content_hash is None


def test_backfill_records_error_for_missing_file(tmp_path: Path):
    db = _make_db(tmp_path)
    db.upsert_photo(
        _photo("photos_library:gone", "photos_library", image_path=str(tmp_path / "gone.png"))
    )

    report = backfill_hashes(db)

    assert report.processed == 0
    assert report.errors == 1
    with db.connect() as conn:
        row = conn.execute("SELECT stage FROM index_errors").fetchone()
    assert row["stage"] == "hash_backfill"


def test_backfill_counts_undecodable_image_as_dhash_failed(tmp_path: Path):
    db = _make_db(tmp_path)
    raw = tmp_path / "shot.dng"
    raw.write_bytes(b"raw bytes that PIL cannot decode")
    db.upsert_photo(_photo("photos_library:raw", "photos_library", image_path=str(raw)))

    report = backfill_hashes(db)

    assert report.processed == 1
    assert report.dhash_failed == 1
    row = db.get_photo("photos_library:raw")
    assert row.content_hash is not None
    assert row.perceptual_hash is None


def test_backfill_respects_limit(tmp_path: Path):
    db = _make_db(tmp_path)
    for i in range(3):
        img = tmp_path / f"l{i}.png"
        _save_png(img, seed=10 + i)
        db.upsert_photo(_photo(f"photos_library:l{i}", "photos_library", image_path=str(img)))

    report = backfill_hashes(db, limit=2)

    assert report.processed == 2


def test_mark_prefers_photos_library_over_local(tmp_path: Path):
    db = _make_db(tmp_path)
    db.upsert_photo(_photo("photos_library:u1", "photos_library", content_hash="h1"))
    db.upsert_photo(_photo("local:a", "local", content_hash="h1"))

    report = mark_cross_source_duplicates(db)

    assert report.groups == 1
    assert report.marked == 1
    assert db.get_photo("local:a").duplicate_of == "photos_library:u1"
    assert db.get_photo("photos_library:u1").duplicate_of is None


def test_mark_prefers_local_over_takeout(tmp_path: Path):
    db = _make_db(tmp_path)
    db.upsert_photo(_photo("local:a", "local", content_hash="h2"))
    db.upsert_photo(_photo("google_takeout:b", "google_takeout", content_hash="h2"))

    mark_cross_source_duplicates(db)

    assert db.get_photo("google_takeout:b").duplicate_of == "local:a"


def test_mark_ignores_same_source_and_null_hash(tmp_path: Path):
    db = _make_db(tmp_path)
    db.upsert_photo(_photo("photos_library:u1", "photos_library", content_hash="h3"))
    db.upsert_photo(_photo("photos_library:u2", "photos_library", content_hash="h3"))
    db.upsert_photo(_photo("local:nohash1", "local"))
    db.upsert_photo(_photo("photos_library:nohash2", "photos_library"))

    report = mark_cross_source_duplicates(db)

    assert report.groups == 0
    assert report.marked == 0
    assert db.get_photo("photos_library:u2").duplicate_of is None


def test_mark_mixed_group_keeps_same_source_sibling(tmp_path: Path):
    """canonical과 같은 소스의 형제 행은 마킹하지 않는다 — ADR-0002(asset=identity)."""
    db = _make_db(tmp_path)
    db.upsert_photo(_photo("photos_library:u1", "photos_library", content_hash="h6"))
    db.upsert_photo(_photo("photos_library:u2", "photos_library", content_hash="h6"))
    db.upsert_photo(_photo("local:a", "local", content_hash="h6"))

    report = mark_cross_source_duplicates(db)

    assert report.marked == 1
    assert db.get_photo("local:a").duplicate_of == "photos_library:u1"
    assert db.get_photo("photos_library:u2").duplicate_of is None


def test_mark_rerun_clears_stale_marks(tmp_path: Path):
    db = _make_db(tmp_path)
    db.upsert_photo(_photo("photos_library:u1", "photos_library", content_hash="h4"))
    db.upsert_photo(_photo("local:a", "local", content_hash="h4"))
    mark_cross_source_duplicates(db)

    db.update_photo_hashes("local:a", content_hash="h5")
    report = mark_cross_source_duplicates(db)

    assert report.marked == 0
    assert db.get_photo("local:a").duplicate_of is None

import json
from pathlib import Path

import pandas as pd

from eddr.db.repository import EddrDatabase
from eddr.db.source_loader import load_available_sources


def test_load_available_sources_promotes_local_takeout_and_exported_photos(tmp_path: Path):
    cache_dir = tmp_path / "eda_cache"
    takeout_dir = tmp_path / "google_photos"
    export_dir = tmp_path / "photos_export"
    cache_dir.mkdir()
    takeout_dir.mkdir()
    export_dir.mkdir()

    local_image = tmp_path / "local.jpg"
    local_image.write_bytes(b"local")
    takeout_image = tmp_path / "takeout.jpg"
    takeout_image.write_bytes(b"takeout")
    photos_image = export_dir / "PHOTOS-1.jpg"
    photos_image.write_bytes(b"photos")

    pd.DataFrame(
        [
            {
                "source": "local",
                "local_path": str(local_image),
                "thumb_path": str(local_image),
                "filename_norm": "LOCAL.JPG",
                "relative_folder": ".",
                "folder_top": "local",
                "exif_date": "2020-01-02T03:04:05+00:00",
                "has_exif_gps": True,
                "gps_lat": 37.5,
                "gps_lng": 127.0,
                "width": 1000,
                "height": 800,
                "blake3": "localhash",
                "dhash": "aaaa",
                "bucket": "icloud_new",
            }
        ]
    ).to_parquet(cache_dir / "vision_manifest.parquet")

    pd.DataFrame(
        [
            {
                "uuid": "PHOTOS-1",
                "filename": "IMG_0001.HEIC",
                "date": "2021-01-02T03:04:05+00:00",
                "lat": 36.1,
                "lng": 128.2,
                "hidden": False,
                "screenshot": False,
                "ismovie": False,
                "burst": False,
                "burst_selected": True,
                "width": 4032,
                "height": 3024,
                "camera_make": "Apple",
                "camera_model": "iPhone",
            },
            {
                "uuid": "SCREENSHOT",
                "filename": "IMG_0002.PNG",
                "date": "2021-01-03T03:04:05+00:00",
                "lat": None,
                "lng": None,
                "hidden": False,
                "screenshot": True,
                "ismovie": False,
                "burst": False,
                "burst_selected": True,
                "width": 4032,
                "height": 3024,
            },
        ]
    ).to_parquet(cache_dir / "photos_meta.parquet")

    (takeout_dir / "manifest.jsonl").write_text(
        json.dumps(
            {
                "source": "google_takeout",
                "source_uri": "2011/takeout.jpg",
                "staged_path": str(takeout_image),
                "content_hash": "takeouthash",
                "taken_at": "2011-04-02T15:14:20+00:00",
                "latitude": None,
                "longitude": None,
                "original_filename": "takeout.jpg",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    report = load_available_sources(
        db,
        eda_cache_dir=cache_dir,
        takeout_manifest=takeout_dir / "manifest.jsonl",
        photos_export_dir=export_dir,
    )

    assert report.loaded == 3
    assert report.skipped == 1
    assert db.count_photos() == 3
    assert db.get_photo("photos_library:PHOTOS-1").image_path == str(photos_image)
    assert db.get_photo("photos_library:SCREENSHOT") is None


def test_load_available_sources_skips_videos_in_vision_manifest(tmp_path: Path):
    cache_dir = tmp_path / "eda_cache"
    cache_dir.mkdir()
    video = tmp_path / "clip.MOV"
    video.write_bytes(b"video")
    image = tmp_path / "still.jpg"
    image.write_bytes(b"still")

    pd.DataFrame(
        [
            {"source": "local", "local_path": str(video), "blake3": "vidhash"},
            {"source": "local", "local_path": str(image), "blake3": "imghash"},
        ]
    ).to_parquet(cache_dir / "vision_manifest.parquet")

    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    report = load_available_sources(
        db,
        eda_cache_dir=cache_dir,
        takeout_manifest=tmp_path / "missing.jsonl",
        photos_export_dir=tmp_path / "no_export",
    )

    assert report.loaded == 1
    assert report.skipped == 1
    assert db.count_photos() == 1
    assert db.get_photo("local:imghash") is not None
    assert db.get_photo("local:vidhash") is None


def test_load_available_sources_skips_videos_in_takeout_manifest(tmp_path: Path):
    cache_dir = tmp_path / "eda_cache"
    cache_dir.mkdir()
    takeout_dir = tmp_path / "google_photos"
    takeout_dir.mkdir()

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    image = tmp_path / "takeout.jpg"
    image.write_bytes(b"takeout")

    rows = [
        {
            "source": "google_takeout",
            "source_uri": "2011/clip.mp4",
            "staged_path": str(video),
            "content_hash": "vidhash",
        },
        {
            "source": "google_takeout",
            "source_uri": "2011/takeout.jpg",
            "staged_path": str(image),
            "content_hash": "imghash",
        },
    ]
    (takeout_dir / "manifest.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )

    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    report = load_available_sources(
        db,
        eda_cache_dir=cache_dir,
        takeout_manifest=takeout_dir / "manifest.jsonl",
        photos_export_dir=tmp_path / "no_export",
    )

    assert report.loaded == 1
    assert report.skipped == 1
    assert report.errors == 0
    assert db.get_photo("google_takeout:imghash") is not None
    assert db.get_photo("google_takeout:vidhash") is None


def test_load_available_sources_ignores_videos_in_photos_export(tmp_path: Path):
    cache_dir = tmp_path / "eda_cache"
    cache_dir.mkdir()
    export_dir = tmp_path / "photos_export"
    export_dir.mkdir()
    (export_dir / "PHOTOS-LIVE.mov").write_bytes(b"live video")

    pd.DataFrame(
        [
            {
                "uuid": "PHOTOS-LIVE",
                "hidden": False,
                "screenshot": False,
                "ismovie": False,
                "burst": False,
                "burst_selected": True,
                "width": 4032,
                "height": 3024,
            }
        ]
    ).to_parquet(cache_dir / "photos_meta.parquet")

    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    load_available_sources(
        db,
        eda_cache_dir=cache_dir,
        takeout_manifest=tmp_path / "missing.jsonl",
        photos_export_dir=export_dir,
    )

    photo = db.get_photo("photos_library:PHOTOS-LIVE")
    assert photo is not None
    assert photo.image_path is None
    assert photo.indexing_status == "missing_image"


def test_load_available_sources_treats_missing_boolean_flags_as_false(tmp_path: Path):
    cache_dir = tmp_path / "eda_cache"
    cache_dir.mkdir()
    export_dir = tmp_path / "photos_export"
    export_dir.mkdir()
    photos_image = export_dir / "PHOTOS-NULLS.jpg"
    photos_image.write_bytes(b"photos")

    pd.DataFrame(
        [
            {
                "uuid": "PHOTOS-NULLS",
                "filename": "IMG_0003.HEIC",
                "date": "2021-01-02T03:04:05+00:00",
                "lat": None,
                "lng": None,
                "hidden": None,
                "screenshot": None,
                "ismovie": None,
                "burst": None,
                "burst_selected": None,
                "width": 1200,
                "height": 800,
            }
        ]
    ).to_parquet(cache_dir / "photos_meta.parquet")

    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    report = load_available_sources(
        db,
        eda_cache_dir=cache_dir,
        takeout_manifest=tmp_path / "missing.jsonl",
        photos_export_dir=export_dir,
    )

    assert report.loaded == 1
    assert db.get_photo("photos_library:PHOTOS-NULLS") is not None

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from eddr.db.repository import EddrDatabase
from eddr.db.source_loader import (
    _iso_or_none,
    load_available_sources,
    normalize_taken_at_backfill,
    normalize_taken_at_kst,
)


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


def test_load_available_sources_normalizes_exif_taken_at(tmp_path: Path):
    cache_dir = tmp_path / "eda_cache"
    cache_dir.mkdir()
    image = tmp_path / "exif.jpg"
    image.write_bytes(b"exif")

    pd.DataFrame(
        [
            {
                "source": "local",
                "local_path": str(image),
                "blake3": "exifhash",
                "exif_date": "2018:04:10 18:38:51",
            }
        ]
    ).to_parquet(cache_dir / "vision_manifest.parquet")

    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    load_available_sources(
        db,
        eda_cache_dir=cache_dir,
        takeout_manifest=tmp_path / "missing.jsonl",
        photos_export_dir=tmp_path / "no_export",
    )

    assert db.get_photo("local:exifhash").taken_at == "2018-04-10T18:38:51+09:00"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2018:04:10 18:38:51", "2018-04-10T18:38:51+09:00"),
        ("2020-01-02T03:04:05+00:00", "2020-01-02T12:04:05+09:00"),
        ("0000:00:00 00:00:00", None),
        (datetime(2021, 1, 2, 3, 4, 5), "2021-01-02T03:04:05+09:00"),
        (None, None),
    ],
)
def test_iso_or_none_normalizes_exif_datetime(value, expected):
    assert _iso_or_none(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # aware UTC(마이크로초 없음) → 인스턴트 보존 KST 변환
        ("2016-04-20T00:10:06+00:00", "2016-04-20T09:10:06+09:00"),
        # aware UTC(마이크로초 있음) → 마이크로초 보존
        ("2017-06-13T06:44:43.770000+00:00", "2017-06-13T15:44:43.770000+09:00"),
        # naive(local) → 벽시계 보존, +09:00 라벨만 부여
        ("2018-04-10T18:38:51", "2018-04-10T18:38:51+09:00"),
        # 이미 +09:00 → 멱등(항등)
        ("2016-04-20T09:10:06+09:00", "2016-04-20T09:10:06+09:00"),
        # 타 오프셋 → 인스턴트 보존 KST 변환
        ("2018-07-01T12:00:00+02:00", "2018-07-01T19:00:00+09:00"),
        # Z 접미사(UTC) → KST 변환
        ("2020-01-02T03:04:05Z", "2020-01-02T12:04:05+09:00"),
        # None → None
        (None, None),
        # 파싱 불가 → 원문 보존(방어)
        ("not-a-date", "not-a-date"),
    ],
)
def test_normalize_taken_at_kst(value, expected):
    assert normalize_taken_at_kst(value) == expected


def test_normalize_taken_at_kst_is_idempotent():
    once = normalize_taken_at_kst("2017-06-13T06:44:43.770000+00:00")
    assert normalize_taken_at_kst(once) == once


def test_load_available_sources_normalizes_aware_taken_at_to_kst(tmp_path: Path):
    cache_dir = tmp_path / "eda_cache"
    cache_dir.mkdir()
    image = tmp_path / "aware.jpg"
    image.write_bytes(b"aware")

    pd.DataFrame(
        [
            {
                "source": "local",
                "local_path": str(image),
                "blake3": "awarehash",
                "exif_date": "2020-01-02T03:04:05+00:00",
            }
        ]
    ).to_parquet(cache_dir / "vision_manifest.parquet")

    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    load_available_sources(
        db,
        eda_cache_dir=cache_dir,
        takeout_manifest=tmp_path / "missing.jsonl",
        photos_export_dir=tmp_path / "no_export",
    )

    assert db.get_photo("local:awarehash").taken_at == "2020-01-02T12:04:05+09:00"


def test_normalize_taken_at_backfill_snapshots_converts_and_is_idempotent(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    # 정규화 전 raw UTC/naive 값을 직접 심는다(로더 정규화를 우회).
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO photos (id, source, source_uri, taken_at) VALUES (?, ?, ?, ?)",
            [
                ("photos_library:a", "photos_library", "a", "2017-06-13T06:44:43.770000+00:00"),
                ("local:b", "local", "b", "2018-04-10T18:38:51"),
                ("google_takeout:c", "google_takeout", "c", None),
            ],
        )

    report = normalize_taken_at_backfill(db)

    # 원본 스냅샷: taken_at 있던 2건만
    assert report.raw_snapshotted == 2
    assert db.get_photo("photos_library:a").taken_at == "2017-06-13T15:44:43.770000+09:00"
    # naive는 벽시계 보존(시각 불변, +09:00만)
    assert db.get_photo("local:b").taken_at == "2018-04-10T18:38:51+09:00"
    # NULL은 불변
    assert db.get_photo("google_takeout:c").taken_at is None
    # aware는 달력일 변경(06:44 UTC → 15:44 KST, 같은 날), local은 미변경
    assert report.changed_by_source == {"photos_library": 1, "local": 1}
    assert report.calendar_day_changed_by_source == {}
    assert report.remaining_without_kst == 0

    # 원본 보존 확인(raw 컬럼)
    with db.connect() as conn:
        raw = conn.execute(
            "SELECT taken_at_raw FROM photos WHERE id = 'photos_library:a'"
        ).fetchone()[0]
    assert raw == "2017-06-13T06:44:43.770000+00:00"

    # 멱등 재실행: 변환 0건, 스냅샷 0건(이미 raw 있음)
    again = normalize_taken_at_backfill(db)
    assert again.raw_snapshotted == 0
    assert again.changed_by_source == {}
    assert again.remaining_without_kst == 0


def test_normalize_taken_at_backfill_counts_calendar_day_change(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    with db.connect() as conn:
        # 22:00 UTC → 07:00 KST 익일 — 달력일이 바뀐다
        conn.execute(
            "INSERT INTO photos (id, source, source_uri, taken_at)"
            " VALUES ('photos_library:d', 'photos_library', 'd', '2019-06-01T22:00:00+00:00')"
        )

    report = normalize_taken_at_backfill(db)
    assert db.get_photo("photos_library:d").taken_at == "2019-06-02T07:00:00+09:00"
    assert report.calendar_day_changed_by_source == {"photos_library": 1}

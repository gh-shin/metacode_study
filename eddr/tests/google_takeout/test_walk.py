import json
from datetime import date
from pathlib import Path

from eddr.google_takeout.walk import build_records, in_date_range


def _img(p: Path) -> None:
    from PIL import Image

    Image.new("RGB", (4, 4), (10, 20, 30)).save(p)


def _sc(p: Path, ts: str) -> None:
    p.write_text(json.dumps({"photoTakenTime": {"timestamp": ts}}), encoding="utf-8")


def test_in_date_range():
    lo, hi = date(2011, 1, 1), date(2021, 1, 1)
    assert in_date_range(date(2015, 6, 1), lo, hi)
    assert in_date_range(date(2011, 1, 1), lo, hi)  # 하한 포함
    assert not in_date_range(date(2021, 1, 1), lo, hi)  # 상한 제외
    assert not in_date_range(date(2010, 12, 31), lo, hi)


def test_build_records_uses_sidecar(tmp_path: Path):
    media = tmp_path / "IMG_9.jpg"
    _img(media)
    _sc(tmp_path / "IMG_9.jpg.supplemental-metadata.json", "1439616078")  # 2015
    records = build_records(tmp_path)
    assert len(records) == 1
    assert records[0].taken_at.year == 2015
    assert records[0].source_uri.endswith("IMG_9.jpg")


def test_build_records_skips_json_and_nonmedia(tmp_path: Path):
    _img(tmp_path / "a.jpg")
    _sc(tmp_path / "a.jpg.supplemental-metadata.json", "1439616078")
    (tmp_path / "metadata.json").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    records = build_records(tmp_path)
    assert len(records) == 1  # a.jpg만


def test_build_records_survives_bad_sidecar(tmp_path: Path):
    media = tmp_path / "BAD.jpg"
    _img(media)
    (tmp_path / "BAD.jpg.supplemental-metadata.json").write_text("{not json", encoding="utf-8")
    records = build_records(tmp_path)
    assert len(records) == 1  # 망가진 사이드카에도 record는 생성
    assert records[0].taken_at is None  # 파싱 실패 → 사이드카 시각 없음, 생성 img엔 EXIF date 없음


def test_build_records_filename_date_fallback(tmp_path: Path):
    # 사이드카·EXIF 없는 파일, 파일명에 YYYYMMDD_HHMMSS
    media = tmp_path / "20130323_180435-ACTION.jpg"
    _img(media)
    records = build_records(tmp_path)
    assert len(records) == 1
    assert records[0].taken_at is not None
    assert records[0].taken_at.year == 2013 and records[0].taken_at.month == 3


def test_build_records_fb_img_timestamp(tmp_path: Path):
    media = tmp_path / "FB_IMG_1372000000000.jpg"  # Unix ms → 2013
    _img(media)
    records = build_records(tmp_path)
    assert records[0].taken_at is not None
    assert records[0].taken_at.year == 2013


def test_build_records_no_date_when_unparseable(tmp_path: Path):
    media = tmp_path / "_DSC2120.jpg"  # 사이드카·EXIF·파일명 모두 날짜 없음
    _img(media)
    records = build_records(tmp_path)
    assert records[0].taken_at is None

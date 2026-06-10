import json
from datetime import UTC
from pathlib import Path

from eddr.google_takeout.sidecar import find_sidecar, parse_sidecar


def _write(p: Path, payload: dict) -> None:
    p.write_text(json.dumps(payload), encoding="utf-8")


def test_find_exact_supplemental(tmp_path: Path):
    (tmp_path / "IMG_1.jpg").touch()
    sc = tmp_path / "IMG_1.jpg.supplemental-metadata.json"
    _write(sc, {})
    assert find_sidecar(tmp_path / "IMG_1.jpg") == sc


def test_find_truncated_sidecar(tmp_path: Path):
    media = tmp_path / "IMG_20230815_142536.jpg"
    media.touch()
    # 신형 접미사가 46자 한도로 절단된 케이스
    sc = tmp_path / "IMG_20230815_142536.jpg.supplemental-metad.json"
    _write(sc, {})
    assert find_sidecar(media) == sc


def test_find_edited_falls_back_to_base(tmp_path: Path):
    (tmp_path / "IMG_2-edited.jpg").touch()
    sc = tmp_path / "IMG_2.jpg.supplemental-metadata.json"
    _write(sc, {})
    assert find_sidecar(tmp_path / "IMG_2-edited.jpg") == sc


def test_parse_sidecar_fields(tmp_path: Path):
    sc = tmp_path / "x.json"
    _write(
        sc,
        {
            "title": "x.jpg",
            "description": "바다",
            "photoTakenTime": {"timestamp": "1439616078"},
            "geoData": {"latitude": 37.5, "longitude": 127.0},
            "people": [{"name": "철수"}],
        },
    )
    meta = parse_sidecar(sc)
    assert meta.taken_at.tzinfo == UTC
    assert meta.taken_at.year == 2015
    assert (meta.latitude, meta.longitude) == (37.5, 127.0)
    assert meta.description == "바다"
    assert meta.people == ["철수"]


def test_parse_sidecar_zero_geo_is_none(tmp_path: Path):
    sc = tmp_path / "y.json"
    _write(
        sc,
        {
            "photoTakenTime": {"timestamp": "1439616078"},
            "geoData": {"latitude": 0.0, "longitude": 0.0},
        },
    )
    meta = parse_sidecar(sc)
    assert meta.latitude is None and meta.longitude is None


def test_find_sidecar_returns_none_when_missing(tmp_path: Path):
    (tmp_path / "IMG_99.jpg").touch()
    assert find_sidecar(tmp_path / "IMG_99.jpg") is None


def test_find_exact_plain_json(tmp_path: Path):
    (tmp_path / "OLD.jpg").touch()
    sc = tmp_path / "OLD.jpg.json"
    _write(sc, {})
    assert find_sidecar(tmp_path / "OLD.jpg") == sc


def test_find_edited_korean_falls_back_to_base(tmp_path: Path):
    (tmp_path / "IMG_3-수정됨.jpg").touch()
    sc = tmp_path / "IMG_3.jpg.supplemental-metadata.json"
    _write(sc, {})
    assert find_sidecar(tmp_path / "IMG_3-수정됨.jpg") == sc

import json
from datetime import UTC, datetime
from pathlib import Path

from eddr.google_takeout.stage import blake3_hex, dedup_by_content, stage_records
from eddr.google_takeout.walk import MediaRecord


def _rec(path: Path, uri: str) -> MediaRecord:
    return MediaRecord(
        path=path,
        source_uri=uri,
        taken_at=datetime(2015, 6, 1, tzinfo=UTC),
        latitude=None,
        longitude=None,
        description="",
        people=[],
        original_filename=path.name,
    )


def test_blake3_hex_content_addressed(tmp_path: Path):
    a = tmp_path / "a.bin"
    a.write_bytes(b"hello")
    b = tmp_path / "b.bin"
    b.write_bytes(b"hello")  # 다른 경로, 같은 내용
    c = tmp_path / "c.bin"
    c.write_bytes(b"world")
    assert blake3_hex(a) == blake3_hex(b)  # 내용 동일 → 해시 동일
    assert blake3_hex(a) != blake3_hex(c)  # 내용 다름 → 해시 다름
    assert len(blake3_hex(a)) == 64


def test_dedup_keeps_one_per_content(tmp_path: Path):
    (tmp_path / "a_year").mkdir()
    (tmp_path / "z_album").mkdir()
    a = tmp_path / "a_year" / "IMG.jpg"
    a.write_bytes(b"SAME")
    b = tmp_path / "z_album" / "IMG.jpg"
    b.write_bytes(b"SAME")  # 동일 바이트
    c = tmp_path / "a_year" / "OTHER.jpg"
    c.write_bytes(b"DIFF")
    kept = dedup_by_content(
        [
            _rec(b, "z_album/IMG.jpg"),
            _rec(a, "a_year/IMG.jpg"),
            _rec(c, "a_year/OTHER.jpg"),
        ]
    )
    assert len(kept) == 2
    # 동일내용 중복 1장 제거; 보관 규칙은 source_uri 정렬상 먼저(여기선 a_year)
    assert {r.source_uri for r in kept} == {"a_year/IMG.jpg", "a_year/OTHER.jpg"}


def test_stage_writes_files_and_manifest(tmp_path: Path):
    src = tmp_path / "IMG.jpg"
    src.write_bytes(b"DATA")
    out = tmp_path / "out"
    stage_records([_rec(src, "yr/IMG.jpg")], out)
    staged = list((out / "staged").glob("*.jpg"))
    assert len(staged) == 1
    manifest = (out / "manifest.jsonl").read_text(encoding="utf-8").strip().splitlines()
    row = json.loads(manifest[0])
    assert row["source"] == "google_takeout"
    assert row["content_hash"] == staged[0].stem
    assert row["taken_at"].startswith("2015-06-01")
    assert "google_media_key" not in row
    assert set(row.keys()) == {
        "source",
        "source_uri",
        "staged_path",
        "content_hash",
        "taken_at",
        "latitude",
        "longitude",
        "description",
        "people",
        "original_filename",
    }

import json
import zipfile
from datetime import date
from pathlib import Path

from eddr.google_takeout.ingest import extract_raw, ingest


def test_ingest_end_to_end(takeout_tree: Path):
    out = takeout_tree / "out"
    # C=2021-01-01, 하한 2011-01-01 → 2015 사진만, 중복 1장 제거
    n = ingest(
        extracted_root=takeout_tree,
        out_dir=out,
        start=date(2011, 1, 1),
        coverage_start=date(2021, 1, 1),
    )
    rows = [json.loads(line) for line in (out / "manifest.jsonl").read_text("utf-8").splitlines()]
    uris = {r["source_uri"].split("/")[-1] for r in rows}
    assert n == 2  # IMG_A(중복 제거 후 1) + IMG_LONGNAME_0001
    assert "OLD.jpg" not in uris  # 2009 하한 미만 제외
    assert "NEW.jpg" not in uris  # 2023 상한 이상 제외(overlap 회피)
    staged = list((out / "staged").glob("*.jpg"))
    assert len(staged) == 2  # 중복 IMG_A는 1개 파일
    assert all(r["latitude"] in (37.5, None) for r in rows)


def test_extract_raw_unzips(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    extracted = tmp_path / "extracted"
    src = tmp_path / "src.txt"
    src.write_text("hi", encoding="utf-8")
    with zipfile.ZipFile(raw / "takeout-001.zip", "w") as z:
        z.write(src, "Takeout/Google Photos/Photos from 2015/x.txt")
    extract_raw(raw, extracted)
    assert (extracted / "Takeout" / "Google Photos" / "Photos from 2015" / "x.txt").exists()

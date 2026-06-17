from pathlib import Path

import numpy as np
from PIL import Image

from eddr.dedup.hashes import blake3_hex, dhash_hex
from eddr.google_takeout.stage import blake3_hex as takeout_blake3_hex


def _save_gradient_png(path: Path) -> None:
    """가로로 단조 증가하는 그라데이션 — dhash 비트가 전부 1이 되는 결정적 입력."""
    pixels = np.tile(np.linspace(0, 255, 64), (64, 1)).astype("uint8")
    Image.fromarray(pixels, mode="L").save(path)


def test_blake3_hex_matches_takeout_staging_hash(tmp_path: Path):
    p = tmp_path / "a.bin"
    p.write_bytes(b"eddr dedup contract")

    assert blake3_hex(p) == takeout_blake3_hex(p)


def test_blake3_hex_distinguishes_content(tmp_path: Path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"same")
    b.write_bytes(b"different")

    assert len(blake3_hex(a)) == 64
    assert blake3_hex(a) != blake3_hex(b)


def test_dhash_hex_gradient_is_all_ones(tmp_path: Path):
    p = tmp_path / "gradient.png"
    _save_gradient_png(p)

    assert dhash_hex(p) == "ffffffffffffffff"


def test_dhash_hex_reads_heic(tmp_path: Path):
    p = tmp_path / "gradient.heic"
    pixels = np.tile(np.linspace(0, 255, 64), (64, 1)).astype("uint8")
    Image.fromarray(pixels, mode="L").convert("RGB").save(p)

    result = dhash_hex(p)

    assert result is not None
    assert len(result) == 16


def test_dhash_hex_returns_none_for_undecodable(tmp_path: Path):
    p = tmp_path / "raw.dng"
    p.write_bytes(b"not an image at all")

    assert dhash_hex(p) is None

"""파일 해시 계산 — BLAKE3 content hash + dHash perceptual hash.

BLAKE3는 google_takeout staging(`eddr.google_takeout.stage.blake3_hex`)과,
dHash는 EDA(02·03)의 imagehash 산출값과 각각 동일 포맷을 유지해야
cross-source/과거 데이터와 비교 가능하다 (회귀는 tests/dedup이 감시).
"""

from __future__ import annotations

from pathlib import Path

import imagehash
import pillow_heif
from blake3 import blake3
from PIL import Image

pillow_heif.register_heif_opener()


def blake3_hex(path: Path) -> str:
    """파일을 1 MiB 단위로 스트리밍 해시해 BLAKE3 16진수 다이제스트를 반환한다.

    Args:
        path: 해시할 파일 경로.

    Returns:
        64자 BLAKE3 16진수 문자열.
    """
    h = blake3()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dhash_hex(path: Path) -> str | None:
    """이미지의 dHash 64bit 16진수 문자열(16자)을 반환한다.

    RAW 등 PIL이 디코드할 수 없는 파일이면 None을 반환한다.

    Args:
        path: 이미지 파일 경로.

    Returns:
        16자 dHash 16진수 문자열, 디코드 불가 시 None.
    """
    try:
        with Image.open(path) as img:
            return str(imagehash.dhash(img))
    except (OSError, ValueError, SyntaxError):
        return None

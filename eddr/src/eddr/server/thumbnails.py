"""photo_id 키 JPEG 썸네일 — 전 포맷 공통·size 화이트리스트·single-flight (prd §6-c).

브라우저 호환 포맷도 일괄 변환해 모바일 전송량을 줄이고, 캐시 키가 경로가
아닌 photo_id라 파일 이동에 안정적이다 (ADR-0008).
"""

from __future__ import annotations

import threading
from pathlib import Path

# size 화이트리스트 — 그리드(320)·라이트박스(1280) 2단계만 (prd §6-b).
ALLOWED_SIZES = (320, 1280)
_JPEG_QUALITY = 85

# 동일 키 동시 변환 차단(single-flight) — HEIC 그리드 첫 로드 폭주 대비 (prd §9).
_locks_guard = threading.Lock()
_inflight_locks: dict[str, threading.Lock] = {}


def get_thumbnail(source_path: Path, cache_dir: Path, photo_id: str, size: int) -> Path | None:
    """썸네일 캐시 파일 경로를 반환한다 — 없으면 변환해 만든다.

    Args:
        source_path: resolve된 원본 이미지 경로 (실존 검증은 호출 측).
        cache_dir: 캐시 디렉터리 (EDDR_ROOT/data/cache/thumbs).
        photo_id: 캐시 키 — 파일명 비안전 문자는 치환한다.
        size: ALLOWED_SIZES 중 하나 (화이트리스트 검증은 호출 측).

    Returns:
        JPEG 캐시 파일 경로. 변환 실패(손상 파일 등) 시 None.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{_safe_key(photo_id)}_{size}.jpg"
    if target.is_file():
        return target
    key = str(target)
    with _locks_guard:
        lock = _inflight_locks.setdefault(key, threading.Lock())
    try:
        with lock:
            if target.is_file():  # 대기 중 다른 스레드가 완성
                return target
            try:
                _convert(source_path, target, size)
            except Exception:
                return None
    finally:
        with _locks_guard:
            _inflight_locks.pop(key, None)
    return target


def _safe_key(photo_id: str) -> str:
    """photo_id를 파일명으로 안전화한다 (``google_takeout:ab12`` → ``google_takeout_ab12``)."""
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in photo_id)


def _convert(source_path: Path, target: Path, size: int) -> None:
    """원본을 JPEG 썸네일로 변환한다 — 임시 파일에 쓰고 rename(중단 시 손상 캐시 방지)."""
    from PIL import Image, ImageOps
    from pillow_heif import register_heif_opener

    register_heif_opener()
    tmp = target.parent / (target.name + ".tmp")
    with Image.open(source_path) as image:
        # 모바일 사진은 EXIF orientation 의존이 많다 — 픽셀로 굽지 않으면 그리드에서 눕는다.
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((size, size))
        image.save(tmp, format="JPEG", quality=_JPEG_QUALITY)
    tmp.replace(target)

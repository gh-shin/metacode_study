"""썸네일 변환 검증 — photo_id 키 캐시·size 분리·single-flight·실패 격리 (ADR-0008)."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from eddr.server.thumbnails import get_thumbnail


def _source(tmp_path: Path, size: tuple[int, int] = (640, 480)) -> Path:
    path = tmp_path / "src" / "photo.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 50, 50)).save(path)
    return path


def test_creates_photo_id_keyed_jpeg_and_reuses_cache(tmp_path: Path):
    source = _source(tmp_path)
    cache = tmp_path / "thumbs"

    first = get_thumbnail(source, cache, "photos_library:ab12", 320)

    assert first == cache / "photos_library_ab12_320.jpg"  # ':' 치환 — photo_id 키
    with Image.open(first) as image:
        assert image.format == "JPEG" and max(image.size) <= 320
    stamp = first.stat().st_mtime_ns
    assert get_thumbnail(source, cache, "photos_library:ab12", 320) == first
    assert first.stat().st_mtime_ns == stamp  # 캐시 재사용 — 재변환 없음


def test_sizes_are_separate_cache_entries(tmp_path: Path):
    source = _source(tmp_path, size=(2000, 1500))
    cache = tmp_path / "thumbs"

    small = get_thumbnail(source, cache, "p1", 320)
    large = get_thumbnail(source, cache, "p1", 1280)

    assert small != large
    with Image.open(large) as image:
        assert max(image.size) <= 1280


def test_corrupt_source_returns_none_without_cache_residue(tmp_path: Path):
    bad = tmp_path / "bad.heic"
    bad.write_bytes(b"not an image")

    assert get_thumbnail(bad, tmp_path / "thumbs", "p9", 320) is None
    assert not (tmp_path / "thumbs" / "p9_320.jpg").exists()
    assert not (tmp_path / "thumbs" / "p9_320.jpg.tmp").exists()


def test_concurrent_requests_single_flight(tmp_path: Path):
    source = _source(tmp_path, size=(1600, 1200))
    cache = tmp_path / "thumbs"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: get_thumbnail(source, cache, "p1", 1280), range(8)))

    assert all(result == cache / "p1_1280.jpg" for result in results)
    with Image.open(results[0]) as image:
        assert image.format == "JPEG"

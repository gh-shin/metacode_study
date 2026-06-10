from eddr.db.repository import PhotoRecord
from eddr.vision.prompt import build_caption_prompt, find_sensitive_metadata_leaks


def test_metadata_prompt_includes_full_local_metadata_and_privacy_output_rules():
    photo = PhotoRecord(
        id="local:abc",
        source="local",
        source_uri="/Users/shingh/Pictures/trips/jeju/IMG_0001.jpg",
        image_path="/Users/shingh/Pictures/trips/jeju/IMG_0001.jpg",
        taken_at="2020-06-20T19:30:00+09:00",
        latitude=33.450701,
        longitude=126.570667,
        width=4032,
        height=3024,
        camera_make="Apple",
        camera_model="iPhone 15 Pro",
    )

    prompt = build_caption_prompt(photo)

    assert "source_uri: /Users/shingh/Pictures/trips/jeju/IMG_0001.jpg" in prompt
    assert "image_path: /Users/shingh/Pictures/trips/jeju/IMG_0001.jpg" in prompt
    assert "latitude: 33.450701" in prompt
    assert "longitude: 126.570667" in prompt
    assert "taken_at: 2020-06-20T19:30:00+09:00" in prompt
    assert "dimensions: 4032x3024" in prompt
    assert "camera: Apple iPhone 15 Pro" in prompt
    assert "Caption:" in prompt
    assert "Visual details:" in prompt
    assert "Context cues:" in prompt
    assert "Search keywords:" in prompt
    assert "Do not output exact latitude/longitude" in prompt
    assert "Do not output raw file paths" in prompt


def test_metadata_prompt_omits_missing_values_without_stringifying_none():
    photo = PhotoRecord(
        id="photos_library:uuid",
        source="photos_library",
        source_uri="PHOTOS-UUID",
        image_path=None,
    )

    prompt = build_caption_prompt(photo)

    assert "source: photos_library" in prompt
    assert "source_uri: PHOTOS-UUID" in prompt
    assert "image_path:" not in prompt
    assert "latitude:" not in prompt
    assert "longitude:" not in prompt
    assert "dimensions:" not in prompt
    assert "camera:" not in prompt
    assert "None" not in prompt


def test_sensitive_metadata_leak_detector_flags_paths_and_exact_coordinates():
    photo = PhotoRecord(
        id="local:abc",
        source="local",
        source_uri="/Users/shingh/Pictures/trips/jeju/IMG_0001.jpg",
        image_path="/Users/shingh/Pictures/trips/jeju/IMG_0001.jpg",
        latitude=33.450701,
        longitude=126.570667,
    )

    leaks = find_sensitive_metadata_leaks(
        "Context cues: /Users/shingh/Pictures/trips/jeju/IMG_0001.jpg at 33.450701, 126.570667",
        photo,
    )

    assert leaks == ["image_path", "source_uri", "latitude", "longitude", "home_path"]


def test_sensitive_metadata_leak_detector_allows_safe_context():
    photo = PhotoRecord(
        id="local:abc",
        source="local",
        source_uri="/Users/shingh/Pictures/trips/jeju/IMG_0001.jpg",
        image_path="/Users/shingh/Pictures/trips/jeju/IMG_0001.jpg",
        latitude=33.450701,
        longitude=126.570667,
    )

    leaks = find_sensitive_metadata_leaks(
        "Context cues: likely an evening coastal travel scene.",
        photo,
    )

    assert leaks == []

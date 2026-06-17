from eddr.db.repository import PhotoRecord
from eddr.vision.prompt import (
    build_caption_prompt,
    build_prompt_for_photo,
    find_sensitive_metadata_leaks,
)


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


def test_food_guard_prompt_preserves_keyword_contract_and_rejects_unsupported_noodles():
    photo = PhotoRecord(
        id="local:food",
        source="local",
        source_uri="/photos/food.jpg",
        image_path="/photos/food.jpg",
    )

    prompt = build_prompt_for_photo(photo, "p3_hybrid_food_guard")

    assert "Search keywords:" in prompt
    assert 'Use "noodles" only when actual noodle strands are visible' in prompt
    assert "bean sprouts" in prompt
    assert "Do not invent exact dish names" in prompt


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


def test_p4_grounded_prompt_contains_grounding_rules_and_keyword_contract():
    photo = PhotoRecord(
        id="local:grounded",
        source="local",
        source_uri="/photos/grounded.jpg",
        image_path="/photos/grounded.jpg",
    )

    prompt = build_prompt_for_photo(photo, "p4_grounded")

    assert "Grounding rules:" in prompt
    assert "Search keywords:" in prompt
    assert "Do not invent specific proper names" in prompt
    assert "use the more general term" in prompt


def test_p4_grounded_prompt_name_is_registered_in_prompt_names():
    from eddr.vision.prompt import PROMPT_NAMES

    assert "p4_grounded" in PROMPT_NAMES


def test_p4_grounded_prompt_has_no_metadata_hints():
    """p4_grounded는 p3_hybrid 베이스 — 메타데이터 힌트 섹션이 없어야 한다."""
    photo = PhotoRecord(
        id="local:grounded",
        source="local",
        source_uri="/photos/grounded.jpg",
        image_path="/photos/grounded.jpg",
        latitude=37.5,
        longitude=127.0,
    )

    prompt = build_prompt_for_photo(photo, "p4_grounded")

    # 메타데이터 힌트 섹션(v2 베이스)은 포함되지 않아야 함
    assert "latitude:" not in prompt
    assert "longitude:" not in prompt
    assert "Use this local-only metadata" not in prompt


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


def test_p5_grounded_prompt_contains_grounding_rules_and_keyword_contract():
    photo = PhotoRecord(
        id="local:grounded5",
        source="local",
        source_uri="/photos/grounded5.jpg",
        image_path="/photos/grounded5.jpg",
    )

    prompt = build_prompt_for_photo(photo, "p5_grounded")

    assert "Grounding rules:" in prompt
    assert "Search keywords:" in prompt
    assert "Name things as specifically as the visible evidence allows" in prompt
    assert "Note the medium or framing" in prompt


def test_p5_grounded_prompt_name_is_registered_in_prompt_names():
    from eddr.vision.prompt import PROMPT_NAMES

    assert "p5_grounded" in PROMPT_NAMES


def test_p5_grounded_prompt_has_no_metadata_hints():
    """p5_grounded는 메타데이터 힌트 없는 베이스여야 한다."""
    photo = PhotoRecord(
        id="local:grounded5",
        source="local",
        source_uri="/photos/grounded5.jpg",
        image_path="/photos/grounded5.jpg",
        latitude=37.5,
        longitude=127.0,
    )

    prompt = build_prompt_for_photo(photo, "p5_grounded")

    assert "latitude:" not in prompt
    assert "longitude:" not in prompt
    assert "Use this local-only metadata" not in prompt

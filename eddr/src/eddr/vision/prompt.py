"""비전 캡션용 프롬프트 템플릿 및 민감 메타데이터 누출 검사 유틸리티."""

from __future__ import annotations

from eddr.db.repository import PhotoRecord

P3_HYBRID_PROMPT_NAME = "p3_hybrid"
P3_HYBRID_V2_PROMPT_NAME = "p3_hybrid_v2"
P3_HYBRID_FOOD_GUARD_PROMPT_NAME = "p3_hybrid_food_guard"
P4_GROUNDED_PROMPT_NAME = "p4_grounded"
P5_GROUNDED_PROMPT_NAME = "p5_grounded"
PROMPT_NAMES = (
    P3_HYBRID_PROMPT_NAME,
    P3_HYBRID_V2_PROMPT_NAME,
    P3_HYBRID_FOOD_GUARD_PROMPT_NAME,
    P4_GROUNDED_PROMPT_NAME,
    P5_GROUNDED_PROMPT_NAME,
)

P3_HYBRID_PROMPT = """Describe this photo in English for personal photo search.
Write 1-2 natural sentences about the visible scene, then add a concise "Search keywords:" list.
Focus on objects, activity, setting, mood, text visible in the image, and visually grounded details.
Do not guess private identity.
"""

P4_GROUNDED_PROMPT = """Describe this photo in English for personal photo search.
Write 1-2 natural sentences about the visible scene, then add a concise "Search keywords:" list.

Grounding rules:
- Describe only what is clearly visible. Do not assert anything you cannot actually see.
- Before naming a category or a specific thing, first identify the concrete visible features that justify it (shapes, colors, ingredients, materials, text). Name the visible parts, then the category.
- Do not invent specific proper names — exact dish names (for example naengmyeon, ramen, pasta), brand names, place names, or a person's identity — unless the image clearly supports them through visible features or readable text.
- When unsure between similar-looking things (for example noodles vs. bean sprouts vs. shredded vegetables, or a sign vs. a menu), use the more general term or describe the visible features instead of guessing the specific one.
- In Search keywords, include both general terms and the specific visible elements you actually observed; do not add keywords for things that are not visible.

Do not guess private identity.
"""

P5_GROUNDED_PROMPT = """Describe this photo in English for personal photo search.
Write 1-2 natural sentences about the visible scene, then add a concise "Search keywords:" list.

Grounding rules:
- Describe only what is clearly visible. Do not assert anything you cannot actually see.
- Before naming a category or a specific thing, first identify the concrete visible features that justify it (shapes, colors, ingredients, materials, text), then name it.
- Name things as specifically as the visible evidence allows. If a food, object, brand, or place is clearly recognizable (for example salmon, grilled pork, a readable brand name), name it specifically. Only fall back to a general term when the specific identity is genuinely ambiguous.
- Do not invent specific proper names the image does not support — exact dish names, brand names, place names, or a person's identity — when the visible features do not clearly justify them.
- When two similar things are easy to confuse (for example noodles vs. bean sprouts vs. shredded vegetables, soju vs. beer, a sign vs. a menu), look at the concrete visible features and choose the one the evidence supports; if still unclear, describe the visible features instead of guessing.
- Note the medium or framing when it matters: for example a photo of a computer screen or monitor, a screenshot, or an upside-down or rotated photo.
- In Search keywords, include both general terms and the specific visible elements you actually observed; do not add keywords for things that are not visible.

Do not guess private identity.
"""


def build_prompt_for_photo(photo: PhotoRecord, prompt_name: str) -> str:
    """프롬프트 이름에 따라 사진에 적합한 프롬프트 문자열을 반환한다.

    Args:
        photo: 프롬프트 생성에 사용할 사진 레코드(메타데이터 참조).
        prompt_name: 사용할 프롬프트 이름(``PROMPT_NAMES`` 중 하나).

    Returns:
        완성된 프롬프트 문자열.

    Raises:
        ValueError: ``prompt_name``이 지원하지 않는 값인 경우.
    """
    if prompt_name == P3_HYBRID_PROMPT_NAME:
        return P3_HYBRID_PROMPT
    if prompt_name == P3_HYBRID_V2_PROMPT_NAME:
        return build_caption_prompt(photo)
    if prompt_name == P3_HYBRID_FOOD_GUARD_PROMPT_NAME:
        return build_caption_prompt(photo) + FOOD_GUARD_RULES
    if prompt_name == P4_GROUNDED_PROMPT_NAME:
        return P4_GROUNDED_PROMPT
    if prompt_name == P5_GROUNDED_PROMPT_NAME:
        return P5_GROUNDED_PROMPT
    raise ValueError(f"unknown vision prompt: {prompt_name}")


FOOD_GUARD_RULES = """
Food-specific rules:
- If food is visible, name concrete visible ingredients before naming a dish.
- Distinguish noodles, pasta, ramen, and rice noodles from bean sprouts, mung bean sprouts, radish strips, onion, shredded vegetables, and other thin pale toppings.
- Use "noodles" only when actual noodle strands are visible. If the image shows sprouts or shredded vegetables, use those words instead.
- Do not invent exact dish names such as naengmyeon, ramen, pasta, pho, curry, or bibimbap unless the image strongly supports them through visible ingredients, shape, table context, or readable text.
- In Search keywords, include generic food terms plus specific visible ingredients. Avoid unsupported food-family keywords.
"""


def build_caption_prompt(photo: PhotoRecord) -> str:
    """사진 메타데이터 힌트를 끼워 넣은 v2 캡션 프롬프트를 만든다 (P3_HYBRID_V2)."""
    metadata = "\n".join(f"- {line}" for line in _metadata_lines(photo))
    return f"""Describe this photo in English for personal photo search.

Use the image as the source of truth. Use this local-only metadata as context hints, but do not quote sensitive metadata verbatim:
{metadata}

Output exactly these sections:
Caption: 1-2 natural sentences about the visible scene.
Visual details: concrete visible objects, activities, setting, mood, composition, and any readable text/OCR.
Context cues: safe context from metadata such as time, season, travel/local clue, or camera context. Do not output exact latitude/longitude. Do not output raw file paths, home directories, or private addresses.
Search keywords: 8-15 concise English keywords or short phrases for retrieval.

Rules:
- Be specific and visually grounded.
- Prefer observable details over guesses.
- Use metadata to enrich context, not to invent unseen events.
- Do not guess private identity.
- Do not output exact latitude/longitude values.
- Do not output raw file paths, source URIs, filenames, or home paths.
"""


def find_sensitive_metadata_leaks(text: str, photo: PhotoRecord) -> list[str]:
    """캡션 텍스트에서 민감 메타데이터 누출 항목 이름을 반환한다.

    ``image_path``, ``source_uri``, ``latitude``, ``longitude``, 홈 경로(``/Users/``)를
    검사하며, 누출이 없으면 빈 리스트를 반환한다.

    Args:
        text: 검사할 캡션 문자열.
        photo: 비교 기준이 되는 사진 레코드.

    Returns:
        누출된 항목의 이름 목록(예: ``["latitude", "home_path"]``). 누출 없으면 빈 리스트.
    """
    leaks: list[str] = []
    if _contains(text, photo.image_path):
        leaks.append("image_path")
    if _contains(text, photo.source_uri):
        leaks.append("source_uri")
    if _contains_any(text, _coordinate_spellings(photo.latitude)):
        leaks.append("latitude")
    if _contains_any(text, _coordinate_spellings(photo.longitude)):
        leaks.append("longitude")
    if "/Users/" in text:
        leaks.append("home_path")
    return leaks


def ensure_caption_has_no_sensitive_metadata(text: str, photo: PhotoRecord) -> None:
    """캡션에 민감 메타데이터가 포함되어 있으면 ValueError를 발생시킨다.

    Args:
        text: 검사할 캡션 문자열.
        photo: 비교 기준이 되는 사진 레코드.

    Raises:
        ValueError: 캡션에 민감 메타데이터가 포함된 경우.
    """
    leaks = find_sensitive_metadata_leaks(text, photo)
    if leaks:
        raise ValueError(f"caption contains sensitive metadata: {', '.join(leaks)}")


def _metadata_lines(photo: PhotoRecord) -> list[str]:
    """사진 메타데이터를 프롬프트 삽입용 문자열 라인 목록으로 변환한다."""
    lines = [f"source: {photo.source}"]
    _append_if_present(lines, "source_uri", photo.source_uri)
    _append_if_present(lines, "image_path", photo.image_path)
    _append_if_present(lines, "taken_at", photo.taken_at)
    if photo.latitude is not None:
        lines.append(f"latitude: {float(photo.latitude):.6f}")
    if photo.longitude is not None:
        lines.append(f"longitude: {float(photo.longitude):.6f}")
    if photo.width is not None and photo.height is not None:
        lines.append(f"dimensions: {photo.width}x{photo.height}")
    camera = " ".join(part for part in [photo.camera_make, photo.camera_model] if _clean(part))
    if camera:
        lines.append(f"camera: {camera}")
    return lines


def _append_if_present(lines: list[str], key: str, value: object | None) -> None:
    text = _clean(value)
    if text:
        lines.append(f"{key}: {text}")


def _clean(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    return text


def _contains(text: str, value: object | None) -> bool:
    needle = _clean(value)
    return bool(needle and needle in text)


def _contains_any(text: str, values: set[str]) -> bool:
    return any(value and value in text for value in values)


def _coordinate_spellings(value: float | None) -> set[str]:
    if value is None:
        return set()
    coord = float(value)
    spellings = {str(value)}
    for precision in range(3, 7):
        spellings.add(f"{coord:.{precision}f}")
    return spellings

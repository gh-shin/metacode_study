"""parse_caption의 bold/plain 키워드 머리말 처리 검증."""

from eddr.query.captions import parse_caption

BOLD_CAPTION = (
    "This is a moody, close-up still life featuring several small objects.\n\n"
    "**Search keywords:** Calligraphy, Chinese writing, still life, macro photography"
)

PLAIN_CAPTION = (
    "This photo captures a scenic view of a paved road cutting through a park.\n\n"
    "Search keywords: Japanese temple, garden road, topiary bushes"
)


def test_parses_bold_header():
    parsed = parse_caption(BOLD_CAPTION)
    assert parsed.body == "This is a moody, close-up still life featuring several small objects."
    assert parsed.keywords == (
        "Calligraphy",
        "Chinese writing",
        "still life",
        "macro photography",
    )


def test_parses_plain_header():
    parsed = parse_caption(PLAIN_CAPTION)
    assert parsed.body == (
        "This photo captures a scenic view of a paved road cutting through a park."
    )
    assert parsed.keywords == ("Japanese temple", "garden road", "topiary bushes")


def test_caption_without_keywords_returns_full_body():
    parsed = parse_caption("A plain caption without any keyword line.")
    assert parsed.body == "A plain caption without any keyword line."
    assert parsed.keywords == ()


def test_header_is_case_insensitive_and_strips_empty_items():
    parsed = parse_caption("Body text.\nsearch keywords: one, , two,")
    assert parsed.body == "Body text."
    assert parsed.keywords == ("one", "two")

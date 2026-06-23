"""캡션 텍스트 파싱 — P3_hybrid 캡션을 서술 본문과 검색 키워드로 분리한다."""

from __future__ import annotations

import re
from dataclasses import dataclass

# P3_hybrid 캡션의 키워드 라인 머리말. 모델 출력에 bold(`**Search keywords:**`)와
# plain(`Search keywords:`) 두 표기가 혼재한다(실DB 2026-06-11: bold 4,370 · plain 5,013).
_KEYWORDS_HEADER = re.compile(r"\*{0,2}Search keywords:\*{0,2}\s*", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedCaption:
    """캡션을 서술 본문과 검색 키워드 목록으로 분리한 결과.

    Attributes:
        body: 키워드 라인을 제외한 서술 본문.
        keywords: 키워드 문자열 튜플. 키워드 라인이 없으면 빈 튜플.
    """

    body: str
    keywords: tuple[str, ...]


def parse_caption(text: str) -> ParsedCaption:
    """캡션 텍스트에서 본문과 `Search keywords:` 키워드 목록을 분리한다.

    bold/plain 두 머리말 표기를 모두 처리하고, 키워드는 콤마 기준으로
    분할해 공백을 정리한다.

    Args:
        text: 원본 캡션 텍스트.

    Returns:
        본문과 키워드 튜플을 담은 ParsedCaption. 키워드 라인이 없으면
        본문에 전체 텍스트가 들어가고 키워드는 빈 튜플이 된다.
    """
    match = _KEYWORDS_HEADER.search(text)
    if match is None:
        return ParsedCaption(body=text.strip(), keywords=())
    body = text[: match.start()].strip()
    keyword_blob = text[match.end() :].strip()
    keywords = tuple(part.strip() for part in keyword_blob.split(",") if part.strip())
    return ParsedCaption(body=body, keywords=keywords)

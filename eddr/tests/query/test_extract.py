"""QueryExtractor 단위 테스트 — fake client 주입, 실제 ollama 호출 없음."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import ollama
import pytest

from eddr.query.extract import (
    EXTRACT_FORMAT,
    ExtractedQuery,
    QueryExtractor,
    build_extract_messages,
)

VALID_PAYLOAD = {
    "keywords_en": ["basalt", "beach", "volcanic rock"],
    "keywords_ko": ["현무암", "해변", "화산암"],
    "date_from": "2024-06-01",
    "date_to": "2024-08-31",
    "countries": [],
    "cities": ["제주"],
}

VALID_RESULT = ExtractedQuery(
    keywords_en=("basalt", "beach", "volcanic rock"),
    date_from="2024-06-01",
    date_to="2024-08-31",
    countries=(),
    cities=("제주",),
    fallback=False,
    keywords_ko=("현무암", "해변", "화산암"),
)

EMPTY_FALLBACK = ExtractedQuery(fallback=True)


def _response(payload: dict) -> dict:
    return {"message": {"content": json.dumps(payload, ensure_ascii=False)}}


class FakeOllamaClient:
    """준비된 응답·예외를 순서대로 돌려주는 가짜 ollama client."""

    def __init__(self, results: list):
        self.results = list(results)
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_extract_parses_valid_response():
    fake = FakeOllamaClient([_response(VALID_PAYLOAD)])
    extractor = QueryExtractor(client=fake)

    result = extractor.extract("작년 여름 제주 현무암 해변")

    assert result == VALID_RESULT
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["model"] == "gemma4:e2b"
    assert call["format"] == EXTRACT_FORMAT
    assert call["options"] == {"temperature": 0}
    assert call["messages"][-1] == {"role": "user", "content": "작년 여름 제주 현무암 해변"}


@pytest.mark.parametrize(
    "first_failure",
    [
        {"message": {"content": "이건 JSON이 아님"}},
        ollama.ResponseError("model busy"),
    ],
    ids=["bad-json", "response-error"],
)
def test_extract_retries_once_then_succeeds(first_failure):
    fake = FakeOllamaClient([first_failure, _response(VALID_PAYLOAD)])
    extractor = QueryExtractor(client=fake)

    result = extractor.extract("제주도 현무암 해변")

    assert result == VALID_RESULT
    assert len(fake.calls) == 2


def test_extract_falls_back_after_two_failures():
    fake = FakeOllamaClient(
        [{"message": {"content": "여전히 JSON 아님"}}, ollama.ResponseError("boom")]
    )
    extractor = QueryExtractor(client=fake)

    result = extractor.extract("은하수 본 사진")

    assert result == EMPTY_FALLBACK
    assert result.keywords_en == ()
    assert result.date_from is None and result.date_to is None
    assert len(fake.calls) == 2


@pytest.mark.parametrize(
    "bad_payload",
    [
        {**VALID_PAYLOAD, "keywords_en": "basalt"},  # 배열이 아닌 문자열
        {**VALID_PAYLOAD, "date_from": "작년 여름"},  # YYYY-MM-DD 위반
        {**VALID_PAYLOAD, "cities": [1, 2]},  # 문자열 아닌 항목
        {k: v for k, v in VALID_PAYLOAD.items() if k != "countries"},  # 필수 키 누락
    ],
    ids=["keywords-not-list", "bad-date", "non-str-city", "missing-key"],
)
def test_extract_schema_violation_falls_back(bad_payload):
    fake = FakeOllamaClient([_response(bad_payload), _response(bad_payload)])
    extractor = QueryExtractor(client=fake)

    result = extractor.extract("아무 질의")

    assert result == EMPTY_FALLBACK
    assert len(fake.calls) == 2


def test_extract_propagates_connection_error_without_retry():
    fake = FakeOllamaClient([ConnectionError("Failed to connect to Ollama")])
    extractor = QueryExtractor(client=fake)

    with pytest.raises(ConnectionError):
        extractor.extract("아무 질의")
    assert len(fake.calls) == 1  # 연결 불가는 재시도 없이 즉시 전파


def test_extract_normalizes_empty_strings():
    payload = {
        "keywords_en": [" trip ", "", "travel"],
        "keywords_ko": ["여행", "", "트래블"],
        "date_from": "",
        "date_to": "null",
        "countries": ["이탈리아"],
        "cities": [],
    }
    fake = FakeOllamaClient([_response(payload)])
    extractor = QueryExtractor(client=fake)

    result = extractor.extract("이탈리아 여행 언제 갔지?")

    assert result.keywords_en == ("trip", "travel")
    assert result.keywords_ko == ("여행", "트래블")
    assert result.date_from is None and result.date_to is None
    assert result.countries == ("이탈리아",)
    assert result.fallback is False


@pytest.mark.parametrize(
    ("countries", "cities", "expected_countries"),
    [
        (["대한민국"], ["부산"], ()),  # 국내 도시 + 거주국 유추 → 거주국 제거
        (["대한민국"], [], ("대한민국",)),  # 도시 없으면 국가 필터 유효 — 유지
        (["이탈리아"], ["로마"], ("이탈리아",)),  # 해외 국가+도시는 그대로
        (["대한민국", "일본"], ["부산"], ("일본",)),  # 거주국만 선별 제거
    ],
    ids=["home-dropped", "home-kept-alone", "foreign-kept", "mixed"],
)
def test_extract_drops_redundant_home_country(countries, cities, expected_countries):
    payload = {
        "keywords_en": ["travel"],
        "keywords_ko": ["여행"],
        "date_from": None,
        "date_to": None,
        "countries": countries,
        "cities": cities,
    }
    fake = FakeOllamaClient([_response(payload)])
    extractor = QueryExtractor(client=fake)

    result = extractor.extract("아무 질의")

    assert result.countries == expected_countries
    assert result.cities == tuple(cities)


def test_build_messages_injects_given_date_and_relative_few_shot():
    messages = build_extract_messages("올해 초 눈", today=date(2026, 6, 12))

    assert messages[0]["role"] == "system"
    assert "2026-06-12" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "올해 초 눈"}
    # 상대날짜 few-shot("작년 여름 바다")의 정답이 기준일에 맞춰 갱신되는지
    relative_answer = json.dumps(
        {
            "keywords_en": ["sea", "beach", "ocean"],
            "keywords_ko": ["바다", "해변", "해양"],
            "date_from": "2025-06-01",
            "date_to": "2025-08-31",
            "countries": [],
            "cities": [],
        },
        ensure_ascii=False,
    )
    assert {"role": "assistant", "content": relative_answer} in messages


def test_build_messages_defaults_to_today_kst():
    today_kst = datetime.now(ZoneInfo("Asia/Seoul")).date()

    messages = build_extract_messages("어제 찍은 사진")

    assert today_kst.isoformat() in messages[0]["content"]

"""질의 추출기 — 한국어 사진 검색 질의에서 검색 조건을 구조화 추출한다 (D26 M3, FR-SEARCH-2).

gemma4:e2b(ollama structured output, temperature 0)로 질의를 ``ExtractedQuery``
(영어 키워드 · 날짜 범위 · 한국어 지명)로 변환한다. 모델 오류·JSON/스키마 실패는
1회 재시도 후 임베딩-only 폴백(전부 빈 값, ``fallback=True``)으로 강등하고,
ollama 연결 자체가 불가한 ``ConnectionError``는 서버 레이어가 503으로 처리하도록
전파한다(prd.md v2 §6-c).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import ollama

from eddr.constants import EXTRACT_MODEL

_KST = ZoneInfo("Asia/Seoul")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ollama structured output 강제용 JSON schema (chat의 format 인자).
EXTRACT_FORMAT: dict = {
    "type": "object",
    "properties": {
        "keywords_en": {"type": "array", "items": {"type": "string"}},
        "keywords_ko": {"type": "array", "items": {"type": "string"}},
        "date_from": {"type": ["string", "null"]},
        "date_to": {"type": ["string", "null"]},
        "countries": {"type": "array", "items": {"type": "string"}},
        "cities": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["keywords_en", "keywords_ko", "date_from", "date_to", "countries", "cities"],
}


@dataclass(frozen=True)
class ExtractedQuery:
    """질의에서 추출한 검색 조건.

    Attributes:
        keywords_en: 영어 캡션 FTS(porter) 매칭용 영어 키워드 — 동의어 2~4개 권장.
        date_from: 촬영일 하한(YYYY-MM-DD). 질의에 시기 표현이 없으면 None.
        date_to: 촬영일 상한(YYYY-MM-DD). 질의에 시기 표현이 없으면 None.
        countries: 한국어 국가명(DB photos.country 표기 — 예: "이탈리아").
        cities: 한국어 도시명(DB photos.city 표기 — 예: "서울특별시", "제주").
        fallback: 추출 실패로 전부 빈 결과면 True(임베딩-only 폴백 신호).
        keywords_ko: keywords_en 의 한국어 표기(표시 전용 — 개수·순서 일치). 검색에는 쓰지 않는다.
    """

    keywords_en: tuple[str, ...] = ()
    date_from: str | None = None
    date_to: str | None = None
    countries: tuple[str, ...] = ()
    cities: tuple[str, ...] = ()
    fallback: bool = False
    keywords_ko: tuple[str, ...] = ()


def build_extract_messages(query: str, today: date | None = None) -> list[dict[str, str]]:
    """추출 프롬프트 메시지(시스템 지시 + few-shot 4건 + 질의)를 만든다.

    오늘 날짜(KST)는 기본적으로 호출 시점에 계산해 주입한다 — 상대 날짜
    ("작년"·"지난달" 등) 해석 기준이 호출마다 갱신되도록 캐시하지 않는다.

    Args:
        query: 한국어 검색 질의 원문.
        today: 상대 날짜 해석 기준일. None이면 현재 KST 날짜.

    Returns:
        ollama chat에 그대로 전달할 메시지 목록.
    """
    if today is None:
        today = datetime.now(_KST).date()
    last_year = today.year - 1
    # "지난 주말" = 가장 최근에 지나간 토~일 (오늘이 주말이면 그 직전 주말).
    days_since_sat = (today.weekday() - 5) % 7 or 7
    last_sat = today - timedelta(days=days_since_sat)
    last_sun = last_sat + timedelta(days=1)
    examples: list[tuple[str, dict]] = [
        (
            "이탈리아 여행 언제 갔지?",
            {
                "keywords_en": ["trip", "travel"],
                "keywords_ko": ["여행", "관광"],
                "date_from": None,
                "date_to": None,
                "countries": ["이탈리아"],
                "cities": [],
            },
        ),
        (
            "은하수 본 사진",
            {
                "keywords_en": ["milky way", "stars", "night sky"],
                "keywords_ko": ["은하수", "별", "밤하늘"],
                "date_from": None,
                "date_to": None,
                "countries": [],
                "cities": [],
            },
        ),
        (
            "제주도 현무암 해변",
            {
                "keywords_en": ["basalt", "beach", "volcanic rock"],
                "keywords_ko": ["현무암", "해변", "화산암"],
                "date_from": None,
                "date_to": None,
                "countries": [],
                "cities": ["제주"],
            },
        ),
        (
            "작년 여름 바다",
            {
                "keywords_en": ["sea", "beach", "ocean"],
                "keywords_ko": ["바다", "해변", "해양"],
                "date_from": f"{last_year}-06-01",
                "date_to": f"{last_year}-08-31",
                "countries": [],
                "cities": [],
            },
        ),
        (
            # 연도 표지 없는 계절 명사 — 날짜를 만들지 않는 패턴 시연 (G05류 과추출 방지).
            "단풍 사진 보여줘",
            {
                "keywords_en": ["autumn leaves", "fall foliage"],
                "keywords_ko": ["단풍", "낙엽"],
                "date_from": None,
                "date_to": None,
                "countries": [],
                "cities": [],
            },
        ),
        (
            # 주말 산술 시연 — 토~일 이틀 범위.
            "지난 주말 캠핑",
            {
                "keywords_en": ["camping", "tent", "outdoor"],
                "keywords_ko": ["캠핑", "텐트", "야외"],
                "date_from": last_sat.isoformat(),
                "date_to": last_sun.isoformat(),
                "countries": [],
                "cities": [],
            },
        ),
    ]
    messages: list[dict[str, str]] = [{"role": "system", "content": _system_prompt(today)}]
    for example_query, answer in examples:
        messages.append({"role": "user", "content": example_query})
        messages.append({"role": "assistant", "content": json.dumps(answer, ensure_ascii=False)})
    messages.append({"role": "user", "content": query})
    return messages


def _system_prompt(today: date) -> str:
    """오늘 날짜(KST)가 주입된 시스템 지시문을 만든다."""
    return (
        "당신은 개인 사진 검색기의 질의 해석기다. "
        "한국어 질의에서 아래 검색 조건만 추출해 JSON으로 답한다.\n"
        f"오늘 날짜: {today.isoformat()} (KST). "
        "'작년'·'지난달' 같은 상대 시기는 이 날짜 기준으로 계산한다.\n"
        "규칙:\n"
        "- keywords_en: 장면·사물·활동을 묘사하는 영어 검색 키워드(동의어 포함 2~4개). "
        "사진 캡션이 영어라서 반드시 영어로 쓴다. "
        "지명(국가·도시·고유 장소명)은 keywords_en에 절대 넣지 않는다 — countries/cities에만. "
        "단 장소 '유형' 명사(절·해변·시장 등)는 영어로 키워드에 넣는다(temple, beach, market).\n"
        "- date_from/date_to: 연도를 특정하는 표지(올해·작년·재작년·N년 전·이번/지난 달·주·주말·"
        "YYYY년·어제 등)가 있을 때만 YYYY-MM-DD 범위로 채운다. "
        "표지 없이 계절·시기 명사만 있으면('봄꽃', '겨울 바다') 반드시 null — 모든 해가 대상이다.\n"
        "- 'N년 전'은 (올해-N)년의 1월 1일~12월 31일. 주말은 토~일 이틀. "
        "계절은 3개월 범위로: 봄=3~5월, 여름=6~8월, 가을=9~11월, 겨울=12~2월(해 넘김).\n"
        "- countries/cities: 질의에 나온 지명만 한국어 그대로 쓴다"
        "(예: 이탈리아, 서울, 제주). 도시에서 국가를 유추해 추가하지 않는다. "
        "장소 언급이 없으면 빈 배열.\n"
        "- keywords_ko: keywords_en 각 항목의 한국어 표기(개수·순서 일치). "
        "표시 전용이며 검색에는 쓰지 않는다.\n"
        "- 질의에 없는 조건을 추측해서 만들지 않는다(과추출 금지)."
    )


class QueryExtractor:
    """gemma4:e2b로 한국어 질의를 구조화 추출하는 해석기."""

    def __init__(
        self,
        model: str = EXTRACT_MODEL,
        host: str | None = None,
        client: ollama.Client | None = None,
    ):
        """추출기를 초기화한다.

        Args:
            model: 추출에 사용할 Ollama 모델 이름.
            host: Ollama 서버 URL. None이면 기본 로컬 호스트를 사용한다.
            client: 직접 주입할 클라이언트(테스트용 fake 등). 지정 시 host보다 우선한다.
        """
        self.model = model
        self.host = host
        if client is not None:
            self._client = client
        else:
            self._client = ollama.Client(host=host) if host else None

    def extract(self, query: str) -> ExtractedQuery:
        """질의에서 검색 조건을 추출한다.

        오늘 날짜(KST)를 호출 시점에 프롬프트에 주입하고, ``EXTRACT_FORMAT``
        스키마로 structured output을 강제한다. 모델 오류·JSON 파싱/스키마 실패는
        1회 재시도하고, 그래도 실패하면 빈 ``ExtractedQuery(fallback=True)``를
        돌려준다(임베딩-only 폴백).

        Args:
            query: 한국어 검색 질의 원문.

        Returns:
            추출된 검색 조건. 추출 실패 시 전부 빈 값 + ``fallback=True``.

        Raises:
            ConnectionError: ollama 서버 연결 자체가 불가한 경우(상위 503 처리용 전파).
        """
        messages = build_extract_messages(query)
        for attempt in range(2):
            try:
                response = self._chat(
                    model=self.model,
                    messages=messages,
                    format=EXTRACT_FORMAT,
                    options={"temperature": 0},
                )
                return _parse_content(response["message"]["content"])
            except (ollama.ResponseError, ValueError, KeyError, TypeError):
                if attempt == 0:
                    continue
        return ExtractedQuery(fallback=True)

    def _chat(self, **kwargs):
        if self._client is not None:
            return self._client.chat(**kwargs)
        return ollama.chat(**kwargs)


def _parse_content(content: str) -> ExtractedQuery:
    """모델 응답 JSON 문자열을 ``ExtractedQuery``로 변환한다.

    Args:
        content: 모델이 돌려준 JSON 문자열.

    Returns:
        파싱된 검색 조건(``fallback=False``).

    Raises:
        ValueError: JSON이 아니거나 스키마(타입·날짜 형식)를 위반한 경우.
        KeyError: 필수 키가 누락된 경우.
    """
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError(f"응답이 JSON 객체가 아님: {data!r}")
    cities = _str_items(data, "cities")
    return ExtractedQuery(
        keywords_en=_str_items(data, "keywords_en"),
        date_from=_opt_date(data, "date_from"),
        date_to=_opt_date(data, "date_to"),
        countries=_drop_redundant_home_country(_str_items(data, "countries"), cities),
        cities=cities,
        fallback=False,
        keywords_ko=_str_items(data, "keywords_ko"),
    )


_HOME_COUNTRY = "대한민국"


def _drop_redundant_home_country(
    countries: tuple[str, ...], cities: tuple[str, ...]
) -> tuple[str, ...]:
    """국내 도시가 있으면 거주국 '대한민국'을 버린다.

    소형 모델이 "부산"에서 "대한민국"을 유추해 끼워 넣는 패턴(벤치 v1·v3 잔존)의
    결정적 후처리 — 장소 필터가 (국가 OR 도시) 스코프라 거주국이 끼면 도시 의도가
    전국으로 풀린다. 도시 없이 국가만 있으면("한국에서 찍은") 유효 조건이라 유지.
    """
    if cities and _HOME_COUNTRY in countries:
        return tuple(c for c in countries if c != _HOME_COUNTRY)
    return countries


def _str_items(data: dict, key: str) -> tuple[str, ...]:
    """문자열 배열 필드를 검증·정규화한다(공백 제거, 빈 항목 제외)."""
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key}는 문자열 배열이어야 함: {value!r}")
    return tuple(item.strip() for item in value if item.strip())


def _opt_date(data: dict, key: str) -> str | None:
    """날짜 필드를 검증한다 — None/빈 문자열/"null"은 None, 그 외는 YYYY-MM-DD 강제."""
    value = data[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key}는 YYYY-MM-DD 문자열 또는 null이어야 함: {value!r}")
    value = value.strip()
    if not value or value.lower() == "null":
        return None
    if not _DATE_RE.match(value):
        raise ValueError(f"{key} 날짜 형식 위반: {value!r}")
    return value

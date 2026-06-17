"""OSM Nominatim 지오코딩 클라이언트(reverse·search) — 1 req/s rate limit 준수.

공개 Nominatim 사용 정책: 절대 최대 1 req/s, 식별 가능한 User-Agent 필수.
응답 지명은 한국어 챗봇 답변에 그대로 쓰도록 accept-language=ko로 요청한다.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE_URL = "https://nominatim.openstreetmap.org"
DEFAULT_USER_AGENT = "eddr/0.1 (personal local photo indexer)"

# Nominatim address dict에서 행정구역을 뽑는 우선순위.
# city: 시/군 단위(서울특별시·평창군·포시타노). village(리)는 district 쪽이다.
# district: 구/동/리 단위(강남구·역삼동·횡계리) — zoom=14 응답 기준.
_CITY_KEYS = ("city", "town", "municipality", "county")
_DISTRICT_KEYS = (
    "borough",
    "suburb",
    "city_district",
    "district",
    "quarter",
    "neighbourhood",
    "village",
)


class GeocodeError(Exception):
    """Nominatim 요청 실패 (네트워크·HTTP·응답 파싱 오류)."""


@dataclass(frozen=True)
class GeocodeResult:
    """reverse geocoding 결과. 바다 등 주소 없는 좌표는 전 필드 None."""

    country: str | None = None
    city: str | None = None
    district: str | None = None
    country_code: str | None = None  # ISO 3166-1 alpha-2 대문자 (trip_countries용)


def parse_nominatim_address(address: dict[str, Any]) -> GeocodeResult:
    """Nominatim address dict에서 country/city/district를 추출한다.

    Args:
        address: Nominatim 응답의 ``address`` 객체.

    Returns:
        우선순위 키 매칭으로 채운 GeocodeResult. 매칭 없는 필드는 None.
    """

    def first(keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = address.get(key)
            if value:
                return str(value)
        return None

    raw_code = address.get("country_code")
    return GeocodeResult(
        country=first(("country",)),
        city=first(_CITY_KEYS),
        district=first(_DISTRICT_KEYS),
        country_code=str(raw_code).upper() if raw_code else None,
    )


@dataclass(frozen=True)
class SearchCandidate:
    """forward geocoding(/search) 후보 한 건.

    Attributes:
        name: Nominatim display_name — accept-language=ko로 한국어 우선 표기.
        latitude: 위도.
        longitude: 경도.
        type: OSM 피처 타입 (예: ``place_of_worship``). 없으면 None.
        address: 행정구역 — reverse와 동일 파서(parse_nominatim_address) 결과.
    """

    name: str
    latitude: float
    longitude: float
    type: str | None
    address: GeocodeResult


def _default_fetch(url: str, user_agent: str, timeout_s: float) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        # /reverse는 dict, /search는 list — 파싱은 호출 측 책임.
        return json.loads(response.read().decode("utf-8"))


class NominatimClient:
    """Nominatim /reverse·/search API 클라이언트.

    요청 간 최소 간격(min_interval_s)을 두 API 합산으로 보장한다 — FastAPI
    sync 라우트가 threadpool에서 병렬 실행되므로 락으로 직렬화한다(요청 중
    락 점유는 단일 사용자 정책상 수용, M4 품질 리뷰 I2). fetch/sleep/clock을
    주입할 수 있어 테스트에서 네트워크·시간 의존 없이 검증한다.

    Attributes:
        base_url: Nominatim 서버 URL.
        min_interval_s: 연속 요청 사이 최소 간격(초).
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval_s: float = 1.0,
        timeout_s: float = 30.0,
        language: str = "ko",
        fetch: Callable[[str], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        """클라이언트를 초기화한다.

        Args:
            base_url: Nominatim 서버 URL.
            user_agent: 요청 식별 User-Agent (공개 서버 정책).
            min_interval_s: 연속 요청 사이 최소 간격(초).
            timeout_s: 요청 타임아웃(초).
            language: 응답 지명 언어 (accept-language 헤더).
            fetch: URL → 파싱된 JSON 함수 — 테스트 주입용. None이면 urllib 기본.
            sleep: 대기 함수 — 테스트 주입용.
            clock: 단조 시계 함수 — 테스트 주입용.
        """
        self.base_url = base_url.rstrip("/")
        self.min_interval_s = min_interval_s
        self._language = language
        self._fetch = fetch or (lambda url: _default_fetch(url, user_agent, timeout_s))
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        self._lock = threading.Lock()

    def reverse(self, lat: float, lng: float) -> GeocodeResult:
        """좌표의 행정구역명을 조회한다.

        Args:
            lat: 위도.
            lng: 경도.

        Returns:
            행정구역 GeocodeResult. Nominatim이 주소를 못 찾으면 전 필드 None.

        Raises:
            GeocodeError: 네트워크·HTTP·파싱 실패.
        """
        query = urllib.parse.urlencode(
            {
                "lat": lat,
                "lon": lng,
                "format": "jsonv2",
                "zoom": 14,
                "accept-language": self._language,
            }
        )
        url = f"{self.base_url}/reverse?{query}"
        with self._lock:
            self._respect_rate_limit()
            try:
                payload = self._fetch(url)
            except Exception as exc:
                raise GeocodeError(f"reverse({lat}, {lng}) 실패: {exc}") from exc
        if "error" in payload:
            return GeocodeResult()
        return parse_nominatim_address(payload.get("address", {}))

    def search(self, query: str, limit: int = 5) -> list[SearchCandidate]:
        """장소 검색어의 좌표 후보를 조회한다 — forward geocoding (S4 수동 지오코딩).

        ``countrycodes``를 지정하지 않아 해외 지명도 검색된다. reverse와 동일한
        min_interval·User-Agent 규율을 공유한다(공개 Nominatim 정책).

        Args:
            query: 자연어 장소 검색어 (예: ``서산 개심사``).
            limit: 최대 후보 수.

        Returns:
            SearchCandidate 리스트 — Nominatim 관련도순. 좌표 없는 항목은 제외.

        Raises:
            GeocodeError: 네트워크·HTTP·파싱 실패.
        """
        params = urllib.parse.urlencode(
            {
                "q": query,
                "format": "jsonv2",
                "addressdetails": 1,
                "accept-language": self._language,
                "limit": limit,
            }
        )
        url = f"{self.base_url}/search?{params}"
        with self._lock:
            self._respect_rate_limit()
            try:
                payload = self._fetch(url)
            except Exception as exc:
                raise GeocodeError(f"search({query!r}) 실패: {exc}") from exc
        candidates: list[SearchCandidate] = []
        # 정상 응답은 list — 오류 dict 등 비정상 형태는 후보 0건으로 본다.
        for item in payload if isinstance(payload, list) else []:
            try:
                latitude, longitude = float(item["lat"]), float(item["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            candidates.append(
                SearchCandidate(
                    name=str(item.get("display_name") or ""),
                    latitude=latitude,
                    longitude=longitude,
                    type=str(item["type"]) if item.get("type") else None,
                    address=parse_nominatim_address(item.get("address") or {}),
                )
            )
        return candidates

    def _respect_rate_limit(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            remaining = self.min_interval_s - (now - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
                now += remaining
        self._last_request_at = now

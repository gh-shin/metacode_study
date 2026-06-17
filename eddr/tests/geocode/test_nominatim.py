import pytest

from eddr.geocode.nominatim import (
    GeocodeError,
    GeocodeResult,
    NominatimClient,
    parse_nominatim_address,
)


def test_parse_korean_city_borough_suburb():
    address = {
        "country": "대한민국",
        "city": "서울특별시",
        "borough": "강남구",
        "suburb": "역삼동",
    }

    assert parse_nominatim_address(address) == GeocodeResult(
        country="대한민국", city="서울특별시", district="강남구"
    )


def test_parse_falls_back_town_and_suburb():
    address = {"country": "이탈리아", "town": "포시타노", "suburb": "몬테페르투소"}

    assert parse_nominatim_address(address) == GeocodeResult(
        country="이탈리아", city="포시타노", district="몬테페르투소"
    )


def test_parse_county_fallback_for_rural():
    address = {"country": "대한민국", "county": "평창군", "village": "횡계리"}

    result = parse_nominatim_address(address)

    assert result.city == "평창군"
    assert result.district == "횡계리"


def test_parse_empty_address_returns_all_none():
    assert parse_nominatim_address({}) == GeocodeResult()


def test_parse_extracts_iso_country_code_uppercase():
    # Nominatim은 ISO 3166-1 alpha-2를 소문자("kr")로 반환 — 표준 대문자로 정규화.
    address = {"country": "대한민국", "country_code": "kr", "city": "서울특별시"}

    assert parse_nominatim_address(address).country_code == "KR"


def test_parse_missing_country_code_is_none():
    assert parse_nominatim_address({"country": "대한민국"}).country_code is None


class _RecordingFetch:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls: list[str] = []

    def __call__(self, url: str) -> dict:
        self.urls.append(url)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_reverse_parses_address_and_builds_url():
    fetch = _RecordingFetch([{"address": {"country": "대한민국", "city": "서울"}}])
    client = NominatimClient(fetch=fetch, sleep=lambda s: None, clock=lambda: 0.0)

    result = client.reverse(37.5, 127.001)

    assert result == GeocodeResult(country="대한민국", city="서울", district=None)
    assert "lat=37.5" in fetch.urls[0]
    assert "lon=127.001" in fetch.urls[0]
    assert "format=jsonv2" in fetch.urls[0]
    assert "accept-language=ko" in fetch.urls[0]


def test_reverse_unable_to_geocode_returns_empty_result():
    fetch = _RecordingFetch([{"error": "Unable to geocode"}])
    client = NominatimClient(fetch=fetch, sleep=lambda s: None, clock=lambda: 0.0)

    assert client.reverse(0.0, -160.0) == GeocodeResult()


def test_reverse_enforces_min_interval_between_requests():
    fetch = _RecordingFetch([{"address": {}}, {"address": {}}])
    sleeps: list[float] = []
    # 첫 요청 t=0, 두 번째 시도 시각 t=0.3 → 0.7초 대기해야 함
    times = iter([0.0, 0.3])
    client = NominatimClient(
        fetch=fetch, sleep=sleeps.append, clock=lambda: next(times), min_interval_s=1.0
    )

    client.reverse(37.5, 127.0)
    client.reverse(37.6, 127.1)

    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.7)


def test_reverse_wraps_fetch_failure_as_geocode_error():
    fetch = _RecordingFetch([OSError("connection refused")])
    client = NominatimClient(fetch=fetch, sleep=lambda s: None, clock=lambda: 0.0)

    with pytest.raises(GeocodeError):
        client.reverse(37.5, 127.0)


def test_search_parses_candidates_and_builds_url():
    fetch = _RecordingFetch(
        [
            [
                {
                    "display_name": "개심사, 개심사로, 운산면, 서산시, 충청남도, 대한민국",
                    "lat": "36.6053",
                    "lon": "126.6182",
                    "type": "place_of_worship",
                    "address": {
                        "country": "대한민국",
                        "city": "서산시",
                        "suburb": "운산면",
                        "country_code": "kr",
                    },
                }
            ]
        ]
    )
    client = NominatimClient(fetch=fetch, sleep=lambda s: None, clock=lambda: 0.0)

    candidates = client.search("개심사")

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.name.startswith("개심사")
    assert candidate.latitude == pytest.approx(36.6053)  # 문자열 lat/lon → float 변환
    assert candidate.longitude == pytest.approx(126.6182)
    assert candidate.type == "place_of_worship"
    # 주소는 reverse와 동일 파서(parse_nominatim_address) — 행정구역 입자 일치.
    assert candidate.address == GeocodeResult(
        country="대한민국", city="서산시", district="운산면", country_code="KR"
    )
    url = fetch.urls[0]
    assert "/search?" in url
    for param in ("format=jsonv2", "addressdetails=1", "accept-language=ko", "limit=5"):
        assert param in url
    # countrycodes 미지정 — 해외 지명(다국어)도 검색된다.
    assert "countrycodes" not in url


def test_search_skips_items_without_coordinates():
    fetch = _RecordingFetch([[{"display_name": "좌표 없는 항목"}, {"lat": "1.5", "lon": "2.5"}]])
    client = NominatimClient(fetch=fetch, sleep=lambda s: None, clock=lambda: 0.0)

    candidates = client.search("어딘가")

    assert len(candidates) == 1
    assert (candidates[0].latitude, candidates[0].longitude) == (1.5, 2.5)


def test_search_non_list_payload_returns_no_candidates():
    # Nominatim 오류 JSON(dict) 등 비정상 형태 — 예외 없이 후보 0건으로 처리.
    fetch = _RecordingFetch([{"error": "Unable to search"}])
    client = NominatimClient(fetch=fetch, sleep=lambda s: None, clock=lambda: 0.0)

    assert client.search("없는곳") == []


def test_search_shares_min_interval_with_reverse():
    # reverse 직후 search — 같은 클라이언트의 1 req/s 간격을 두 API가 공유한다.
    fetch = _RecordingFetch([{"address": {}}, []])
    sleeps: list[float] = []
    times = iter([0.0, 0.3])
    client = NominatimClient(
        fetch=fetch, sleep=sleeps.append, clock=lambda: next(times), min_interval_s=1.0
    )

    client.reverse(37.5, 127.0)
    client.search("개심사")

    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(0.7)


def test_search_wraps_fetch_failure_as_geocode_error():
    fetch = _RecordingFetch([OSError("connection refused")])
    client = NominatimClient(fetch=fetch, sleep=lambda s: None, clock=lambda: 0.0)

    with pytest.raises(GeocodeError):
        client.search("개심사")

# AGENTS.md - src/eddr/geocode

## Purpose

GPS 좌표를 행정구역 정보로 변환하고, 위치 검색 후보를 제공한다. Nominatim network client와 DB cache 기반 batch pipeline으로 나뉜다.

## Read First

- `nominatim.py`: `/reverse`, `/search`, address parsing, `GeocodeError`.
- `pipeline.py`: 좌표 quantize, reverse geocode batch, country_code backfill.
- 호출 CLI: `eddr geocode run`, `eddr geocode backfill-country-code`.
- 관련 API: `src/eddr/server/routes/geocode.py`.
- 관련 테스트: `tests/geocode/`, `tests/server/test_geocode_api.py`.

## Public Surface

| Symbol | Input | Output | Notes |
|---|---|---|---|
| `NominatimClient.reverse(lat, lng)` | 좌표 | `GeocodeResult` | reverse geocoding. |
| `NominatimClient.search(query, limit)` | 장소 검색어 | `list[SearchCandidate]` | manual geocode UI 후보. |
| `parse_nominatim_address(address)` | Nominatim address dict | `GeocodeResult` | country/city/district/country_code 추출. |
| `quantize(value)` | 좌표 float | int | 0.001도 격자 cache key. |
| `geocode_photos(db, client, limit, max_consecutive_errors)` | DB, client, 제한 | `GeocodeReport` | GPS 사진 행정구역 채움. |
| `backfill_country_codes(db, client, max_consecutive_errors)` | DB, client | `CountryCodeBackfillReport` | 기존 cache cell의 ISO code 보강. |

## Inputs

- latitude/longitude.
- Nominatim JSON response.
- DB photos with GPS and missing country.
- 장소 검색어 string.

## Outputs

- `GeocodeResult(country, city, district, country_code)`.
- `SearchCandidate(name, latitude, longitude, type, address)`.
- DB geocode cache rows and photo geo fields.

## Side Effects

- Nominatim HTTP 요청.
- geocode cache와 photo geo fields 갱신.

## Exceptions / Failure Modes

- 네트워크 실패, HTTP error, 응답 파싱 실패는 `GeocodeError`.
- 연속 오류가 `max_consecutive_errors`에 도달하면 batch를 중단하고 `aborted=True`.
- 주소 없는 좌표는 field가 `None`인 `GeocodeResult`가 될 수 있다.

## Invariants

- 좌표 cache key는 3dp quantize다.
- privacy: 외부 reverse geocode로 좌표를 보낼 수 있는 것은 기존 프로젝트 정책에서 수용된 경계다.
- 서버 `/api/geocode/search`는 후보 수를 작게 제한한다.

## Tests

- `pytest tests/geocode tests/server/test_geocode_api.py`

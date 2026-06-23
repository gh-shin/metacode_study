# src/eddr/server/routes

FastAPI route 모음이다. 라우트는 얇게 유지하고, 검색 로직은 `QueryService`,
DB 조회/갱신은 `EddrDatabase`, 지오코딩은 `NominatimClient`로 위임한다.

## 라우트 맵

```mermaid
flowchart TD
  API[/api] --> SEARCH[POST /search]
  API --> STATUS[GET /status, /healthz]
  API --> MAP[GET /map/photos]
  API --> PHOTOS[/photos/*]
  API --> GEOCODE[/geocode/search]
  SEARCH --> RS[run_search -> QueryExtractor + QueryService]
  MAP --> GPS[exposed_gps_points]
  PHOTOS --> DB[EddrDatabase + thumbnails + notes]
  GEOCODE --> NOM[Nominatim forward search]
```

## Search API

`POST /api/search`

| 요청/응답 | 필드 | 의미 |
|---|---|---|
| request | `query` | 한국어 자연어 질의 |
| response | `interpretation` | `keywords_en`, `date_from`, `date_to`, `countries`, `cities`, `fallback`, `keywords_ko`, `answer_type` |
| response | `groups[]` | `date`, `place`, `photos`를 가진 KST 날짜 lane |
| response | `groups[].photos[]` | `photo_id`, `taken_at`, `latitude`, `longitude`, `rank` |
| response | `trip_summary[]` | `trip_id`, `name`, `start_at`, `end_at`, `photo_count`, `country_codes` |
| response | `total` | 검색 결과 사진 수 |

처리 흐름은 `QueryExtractor.extract(gemma4:e2b)` -> `trip_ids_for_places` ->
`QueryService.semantic_search_photos(qwen3-embedding:8b)` -> `group_by_kst_date`다.

## Photos API

| Route | 응답/동작 |
|---|---|
| `GET /api/photos/summary?ids=a,b` | 최대 50개 id의 `photo_id`, `taken_at`, `country`, `city`, `has_location` |
| `GET /api/photos/by-date?date=YYYY-MM-DD` | 해당 KST 날짜의 노출 사진. GPS 없는 사진도 포함 |
| `GET /api/photos/no-location` | `{total_photos, groups}`. 그룹은 `date`, `count`, `sample_photo_ids`, `trip_name` |
| `PUT /api/photos/location` | 좌표 수동 지정 후 reverse-fill. `{updated, country, city, district}` |
| `GET /api/photos/{photo_id}` | canonical detail, 좌표, note 포함 |
| `PUT /api/photos/{photo_id}/note` | note upsert 후 동기 임베딩. `{photo_id, text, embedded}` |
| `DELETE /api/photos/{photo_id}/note` | note, Chroma vector, embeddings ledger 삭제 |
| `GET /api/photos/{photo_id}/thumb?size=256` | 캐시된 썸네일 또는 생성된 썸네일 |
| `GET /api/photos/{photo_id}/original` | 원본 파일 응답 |

`/summary`, `/by-date`, `/no-location`, `/location`은 `/{photo_id}`보다 먼저 등록되어야 한다.
그렇지 않으면 FastAPI path matching이 고정 경로를 photo id로 해석한다.

## Map API

`GET /api/map/photos`는 GeoJSON FeatureCollection을 반환한다.

| 위치 | 필드 | 의미 |
|---|---|---|
| `geometry.coordinates` | `[longitude, latitude]` | GeoJSON 표준 순서 |
| `properties.id` | photo id | 클라이언트 selection key |
| `properties.date` | KST `YYYY-MM-DD` | 날짜 lane/by-date 연결 |

좌표는 `ADR-0009`에서 “내 서버 -> 내 브라우저” 노출이 허용된 로컬 필드다.

## Geocode API

`GET /api/geocode/search?q=<place>`는 Nominatim forward 후보만 반환한다. 저장은 하지 않는다.
후보 선택 후 저장은 `PUT /api/photos/location`이 맡고, 주소는 기존 reverse geocode 경로로 채운다.

## Status API

| Route | 의미 |
|---|---|
| `GET /api/healthz` | liveness 확인 |
| `GET /api/status` | `ready`, `total`, `stages`, `path_health`. `path_health`는 표본 이미지 경로 존재 여부 |

## 예외 처리

| 상황 | status |
|---|---|
| 빈 search query | 422 |
| Ollama 연결 실패 | 503 |
| 잘못된 날짜/좌표/note payload | 422 |
| photo/note 없음 | 404 |

## 검증 방법

- search/map/photos/status: `uv run pytest tests/server`
- geocode API: `uv run pytest tests/server/test_geocode_api.py`

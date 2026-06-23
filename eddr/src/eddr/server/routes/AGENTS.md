# AGENTS.md - src/eddr/server/routes

## Purpose

FastAPI HTTP endpoint 구현 모음이다. 이 폴더는 request/response shape와 HTTP error 변환을 담당하고, 실제 검색/DB/model 로직은 `AppState`의 service로 위임한다.

## Read First

- `search.py`: `POST /api/search`, query extraction and lane grouping.
- `photos.py`: photo detail/summary/date/no-location/manual-location/note/thumb/original.
- `map.py`: `GET /api/map/photos` GeoJSON.
- `geocode.py`: `GET /api/geocode/search`.
- `status.py`: health/status.
- 관련 테스트: `tests/server/`.

## Public Surface

| Route | Function | Input | Output |
|---|---|---|---|
| `POST /api/search` | `search` | body `{query}` | `{interpretation, groups, total}` |
| `GET /api/photos/summary` | `photo_summaries` | `ids` comma string | `{photos}` |
| `GET /api/photos/by-date` | `photos_by_date` | `date` | `{photos}` |
| `GET /api/photos/no-location` | `no_location_groups` | none | `{groups}` |
| `PUT /api/photos/location` | `set_photo_location` | `photo_ids`, lat/lng/address | `{updated}` |
| `GET /api/photos/{photo_id}` | `photo_detail` | photo id | detail JSON |
| `PUT /api/photos/{photo_id}/note` | `put_photo_note` | `{text}` | `{text, embedded}` |
| `DELETE /api/photos/{photo_id}/note` | `delete_photo_note` | photo id | 204 |
| `GET /api/photos/{photo_id}/thumb` | `photo_thumb` | `size` 320/1280 | JPEG |
| `GET /api/photos/{photo_id}/original` | `photo_original` | photo id | original file |
| `GET /api/map/photos` | `map_photos` | none | GeoJSON FeatureCollection |
| `GET /api/geocode/search` | `geocode_search` | `q` | `{candidates}` |
| `GET /api/healthz` | `healthz` | none | liveness JSON |
| `GET /api/status` | `status` | none | readiness/stage/path health |

## Side Effects

- Search route calls local query extractor/model.
- Manual location route updates DB coordinates.
- Note routes update DB, Chroma, embeddings records.
- Thumbnail route writes cache.

## Exceptions / Failure Modes

- Missing/invalid payload becomes HTTP 400/404.
- unknown `photo_id` returns 404.
- note embedding failure can return `embedded=False`.
- thumbnail size is whitelisted.

## Invariants

- Route functions should stay thin; business logic belongs in query/db/geocode/vector packages.
- KST date grouping is done in search/photos date routes.
- Coordinates in API are local browser exposure, not external LLM exposure.

## Tests

- `pytest tests/server`

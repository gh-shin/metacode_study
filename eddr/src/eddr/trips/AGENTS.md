# AGENTS.md - src/eddr/trips

## Purpose

Daily Radius 밖에서 일정 시간 이상 이어지는 GPS 사진 구간을 trip으로 재계산한다. 기존 trip assignment를 지우고 새 segment를 DB에 저장하는 batch pipeline이다.

## Read First

- `cluster.py`: `PhotoPoint`를 `TripSegment`로 묶는 순수 segmentation.
- `pipeline.py`: DB read/reset/insert/assign/finalize 순서.
- 호출 CLI: `eddr trips recompute`.
- 관련 테스트: `tests/trips/`.

## Public Surface

| Symbol | Input | Output | Notes |
|---|---|---|---|
| `segment_trips(points, areas, min_duration_hours, max_gap_hours)` | GPS 사진 점, daily areas, 시간 threshold | `list[TripSegment]` | 순수 계산. |
| `recompute_trips(db, min_duration_hours, max_gap_hours)` | DB와 threshold | `TripRecomputeReport` | DB trip 전체 재계산. |

## Inputs

- `PhotoPoint(photo_id, taken_at, latitude, longitude)`.
- daily radius areas: `(lat, lng, radius_km)`.
- `min_duration_hours`: 기본 24.
- `max_gap_hours`: 기본 72.

## Outputs

- `TripSegment(start_at, end_at, photo_ids, center_lat, center_lng)`.
- DB `trips`, `trip_countries`, `photos.trip_id`.
- `TripRecomputeReport(trips_created, photos_assigned)`.

## Side Effects

- `recompute_trips()`는 기존 trip assignments를 지우고 다시 쓴다.
- 사진 파일, captions, embeddings는 수정하지 않는다.

## Exceptions / Failure Modes

- `taken_at` 파싱 불가 또는 GPS 없음 사진은 clustering 입력에서 제외된다.
- Daily Radius가 잘못되면 trip 결과도 잘못된다.
- 짧은 1박 2일이 24시간 미만이면 기본 threshold에서 누락될 수 있다.

## Invariants

- Trip은 일상 반경 밖 연속 체류 구간이다.
- 국경 이동 자체가 trip split 기준은 아니다. 일상 반경 복귀가 더 강한 신호다.
- recompute는 idempotent batch로 설계한다. 같은 입력이면 같은 결과가 나와야 한다.

## Tests

- `pytest tests/trips`

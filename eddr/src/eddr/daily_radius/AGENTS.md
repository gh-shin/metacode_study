# AGENTS.md - src/eddr/daily_radius

## Purpose

사용자의 일상 활동 반경 후보를 GPS 밀도에서 추정하고, wizard로 확정해 DB에 저장한다. trip segmentation은 이 결과를 “일상 밖” 판정에 사용한다.

## Read First

- `cluster.py`: 좌표 거리 계산과 후보 cluster 생성.
- `wizard.py`: DB GPS 좌표 조회, 후보 표시, 사용자 입력 처리.
- 호출 CLI: `eddr setup daily-radius`.
- 관련 테스트: `tests/daily_radius/`.

## Public Surface

| Symbol | Input | Output | Notes |
|---|---|---|---|
| `AreaCandidate` | center/radius/count/place | dataclass | 후보 영역. |
| `haversine_km(...)` | 두 좌표 | km `float` | 대권 거리. |
| `propose_daily_radius(coords, top_n, cell_deg, merge_radius_km, min_count)` | GPS 좌표 목록 | `list[AreaCandidate]` | 밀도 후보 생성. |
| `propose_candidates(db, top_n, min_count)` | DB, 제한값 | `list[AreaCandidate]` | DB 좌표 + place label. |
| `format_candidate(index, total, candidate)` | 후보 | display string | wizard 표시용. |
| `run_wizard(db, candidates, input_fn, print_fn)` | 후보와 I/O 함수 | 저장 개수 `int` | 사용자 확정 후 DB 저장. |

## Inputs

- 중복 제외 GPS 좌표.
- `top_n`, `min_count`, `cell_deg`, `merge_radius_km`.
- wizard 사용자 입력.

## Outputs

- `AreaCandidate(center_lat, center_lng, radius_km, photo_count, place)`.
- DB `daily_radius_areas`.

## Side Effects

- wizard 실행 시 DB의 daily radius 영역을 교체 저장한다.
- `--propose-only` CLI 경로는 후보 출력만 하고 저장하지 않는다.

## Exceptions / Failure Modes

- GPS가 부족하면 후보가 적거나 없을 수 있다.
- 본가/직장/자주 가는 여행지 같은 애매한 영역은 자동 판단하지 않는다. wizard에서 사용자가 결정한다.

## Invariants

- Daily Radius는 trip 검출의 입력이지 trip 결과가 아니다.
- 좌표 clustering은 후보 제안일 뿐, 최종 truth는 사용자 확정값이다.

## Tests

- `pytest tests/daily_radius`

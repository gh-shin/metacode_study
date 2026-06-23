# AGENTS.md - src/eddr/photos_library

## Purpose

macOS Photos Library의 촬영일 coverage를 빠르게 요약하는 utility 계층이다. 메인 DB 적재가 아니라 coverage 파악용이다.

## Read First

- `coverage.py`: Photos Library 날짜 조회, 연도별 count 요약, 표 출력.
- 관련 테스트: `tests/photos_library/test_coverage.py`.

## Public Surface

| Symbol | Input | Output | Notes |
|---|---|---|---|
| `query_taken_dates()` | Photos Library | `list[datetime]` | osxphotos로 이미지 촬영일 조회. |
| `summarize_years(dates)` | datetime list | `dict[int, int]` | 연도별 count. |
| `print_year_table(year_counts)` | count dict | stdout | 누적 비율 표. |

## Inputs

- local macOS Photos Library.
- datetime list for pure summary tests.

## Outputs

- year count dict.
- stdout table.

## Side Effects

- Photos Library를 읽는다.
- `print_year_table`은 stdout에 출력한다.
- DB를 수정하지 않는다.

## Exceptions / Failure Modes

- macOS Photos 접근 권한 또는 osxphotos 환경 문제.
- 동영상 제외 정책은 query 단계에서 반영한다.

## Invariants

- 이 폴더는 coverage 조사용이다. production source loading은 `photos_export`와 `db.source_loader` 경로를 사용한다.

## Tests

- `pytest tests/photos_library/test_coverage.py`

# AGENTS.md - src/eddr/db

## Purpose

EDDR의 SQLite 저장소와 source loading 경계다. 모든 주요 pipeline은 `EddrDatabase`를 통해 photos, captions, embeddings, geocode, daily radius, trips, notes 상태를 읽고 쓴다.

## Read First

- `repository.py`: DB schema/migration, domain dataclass, query/update methods.
- `source_loader.py`: EDA cache, Photos export, Takeout manifest를 `PhotoRecord`로 변환.
- 호출 CLI: `eddr db init`, `eddr db load-sources`, `eddr db normalize-taken-at`, `eddr db prune-errors`.
- 관련 테스트: `tests/db/`, 일부 통합 테스트는 `tests/server/`, `tests/query/`.

## Public Surface

| Symbol | Role |
|---|---|
| `EddrDatabase` | SQLite 연결, migration, 모든 read/write 메서드. |
| `PhotoRecord` | logical photo 1개. Photos asset/source 파일의 DB 표현. |
| `PhotoQueryFilters` | query layer가 DB filter로 전달하는 검색 조건. |
| `TripRecord`, `DailyRadiusArea`, `GpsPoint`, `PhotoOnDate`, `NoLocationDayGroup` | 서버와 query 계층의 읽기 모델. |
| `load_available_sources` | 사용 가능한 source들을 photos 테이블에 적재. |
| `normalize_taken_at_backfill` | `taken_at`을 KST aware ISO 문자열로 정규화. |

## Inputs

- SQLite DB path.
- EDA cache artifacts.
- Photos export CSV/files.
- Google Takeout `manifest.jsonl`.
- pipeline별 dataclass 또는 primitive fields.

## Outputs

- SQLite tables and migrations.
- `PhotoRecord`/`TripRecord` 등 immutable dataclass.
- `SourceLoadReport`, `NormalizeTakenAtReport`, `DedupReport`, `IndexingStats`.

## Side Effects

- SQLite 파일을 생성/변경한다.
- schema migration을 수행한다.
- source loading, trip assignment, manual geocode, notes 저장 등 상태 변경의 중심이다.

## Exceptions / Failure Modes

- DB file lock, malformed source row, missing image path, invalid timestamp가 가능하다.
- 이 계층은 trust boundary다. 외부 source는 반드시 정규화 후 저장해야 한다.
- `normalize_taken_at_backfill()`은 날짜 의미를 바꾸는 migration이므로 백업 경로와 report를 확인한다.

## Invariants

- `PhotoRecord.id`가 photo identity의 내부 key다.
- `source_uri`는 source별 원본 식별자다.
- runtime 검색 노출은 duplicate/video 등 정책 필터를 DB query에서 반영한다.
- KST 정규화 이후 calendar day 기반 API는 KST 날짜를 기준으로 한다.

## Tests

- `pytest tests/db`
- DB 경로를 쓰는 통합 기능은 관련 패키지 테스트도 함께 확인한다.

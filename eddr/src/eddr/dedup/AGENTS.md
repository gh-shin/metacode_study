# AGENTS.md - src/eddr/dedup

## Purpose

사진 파일 hash를 계산하고 cross-source duplicate를 표시한다. v1 정책은 BLAKE3 동일 content hash 기준으로 중복을 마킹하고, dHash는 perceptual hash 필드 백필에 사용한다.

## Read First

- `hashes.py`: BLAKE3와 dHash 계산.
- `pipeline.py`: DB hash backfill과 duplicate marking.
- 호출 CLI: `eddr dedup backfill-hashes`, `eddr dedup mark`.
- 관련 테스트: `tests/dedup/`.

## Public Surface

| Symbol | Input | Output | Notes |
|---|---|---|---|
| `blake3_hex(path)` | 이미지 파일 경로 | hex digest `str` | streaming hash. |
| `dhash_hex(path)` | 이미지 파일 경로 | 16자 hex `str | None` | 이미지 디코딩 실패 시 `None`. |
| `backfill_hashes(db, limit)` | `EddrDatabase`, optional limit | `HashBackfillReport` | 누락 hash를 계산해 DB 저장. |
| `mark_cross_source_duplicates(db)` | `EddrDatabase` | `DedupMarkReport` | content hash 그룹에서 canonical 외 행에 `duplicate_of` 기록. |

## Inputs

- DB의 `photos.image_path`.
- hash가 비어 있는 photo rows.
- source priority는 repository의 `apply_cross_source_dedup()` 계약을 따른다.

## Outputs

- `photos.content_hash`, `photos.perceptual_hash`.
- `photos.duplicate_of`.
- reports: `processed`, `dhash_failed`, `errors`, `groups`, `marked`.

## Side Effects

- 파일을 읽는다.
- SQLite photos row를 수정한다.
- 이미지 파일 자체는 수정하지 않는다.

## Exceptions / Failure Modes

- 파일 없음, 권한 문제, 이미지 디코딩 실패.
- dHash 실패는 report의 `dhash_failed`로 집계하고 content hash와 분리한다.
- BLAKE3 실패는 errors로 집계된다.

## Invariants

- cross-source duplicate만 마킹한다. 같은 Photos asset 내부 변형 문제를 여기서 새 identity로 만들지 않는다.
- `duplicate_of`는 검색 노출 population을 줄이는 데 사용된다.

## Tests

- `pytest tests/dedup`

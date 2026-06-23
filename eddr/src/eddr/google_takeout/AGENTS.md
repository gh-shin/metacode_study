# AGENTS.md - src/eddr/google_takeout

## Purpose

Google Takeout 사진 export를 EDDR staging 포맷으로 변환한다. zip 해제, 미디어 탐색, JSON sidecar 파싱, 날짜 필터링, content hash dedup, `manifest.jsonl` 기록이 핵심이다.

## Read First

- `ingest.py`: 전체 CLI 순서.
- `walk.py`: 미디어 파일 탐색과 `MediaRecord` 생성.
- `sidecar.py`: Takeout JSON sidecar 파싱.
- `stage.py`: content hash dedup과 staged copy.
- 관련 테스트: `tests/google_takeout/`.

## Public Surface

| Symbol | Input | Output | Notes |
|---|---|---|---|
| `extract_raw(raw_dir, extracted_dir)` | zip들이 있는 raw 디렉터리, 해제 디렉터리 | `None` | zip을 `extracted/`로 푼다. |
| `ingest(extracted_root, out_dir, start, coverage_start)` | 해제 루트, 출력 루트, 날짜 하한 2개 | staged count `int` | build/filter/stage 전체 실행. |
| `build_records(root)` | Takeout 해제 루트 | `list[MediaRecord]` | 재귀적으로 미디어와 sidecar를 읽는다. |
| `filter_by_date(records, lo, hi)` | record 목록, 반열린 날짜 구간 | `list[MediaRecord]` | `[lo, hi)` 범위만 남긴다. |
| `find_sidecar(media_path)` | 미디어 파일 경로 | `Path | None` | 대응 JSON sidecar 탐색. |
| `parse_sidecar(path)` | JSON sidecar | `SidecarMeta` | 시간, 좌표, 설명, 인물 추출. |
| `dedup_by_content(records)` | record 목록 | dedup된 record 목록 | BLAKE3 기준 1개만 유지. |
| `stage_records(records, out_dir)` | record 목록, 출력 루트 | staged count `int` | 파일 복사와 manifest 기록. |

## Inputs

- Takeout zip 또는 해제 디렉터리.
- Takeout JSON sidecar.
- 날짜 기준:
  - `start`: staging에 포함할 최소 촬영일.
  - `coverage_start`: 기존 Photos coverage 시작일. 중복 기간 제거용 상한으로 쓰인다.

## Outputs

- `out_dir/staged/`: staged media files.
- `out_dir/manifest.jsonl`: `db.source_loader`가 읽는 Google Takeout source manifest.
- `MediaRecord`: `path`, `source_uri`, `taken_at`, `latitude`, `longitude`, `description`, `people`, `original_filename`.

## Side Effects

- zip 해제 디렉터리에 파일을 쓴다.
- staged 출력 디렉터리에 파일과 manifest를 쓴다.
- 메인 DB는 직접 수정하지 않는다.

## Exceptions / Failure Modes

- 손상 zip, 읽을 수 없는 JSON, EXIF 부재, 날짜 파싱 실패가 가능하다.
- sidecar가 없으면 파일명/EXIF 기반 fallback으로 record를 만든다.
- content hash 계산은 파일 I/O 오류를 그대로 노출한다.

## Invariants

- 날짜 필터는 `[lo, hi)` 반열린 구간이다.
- `source_uri` 정렬 순서가 content dedup tie-breaker다.
- Google Takeout 적재는 main DB 통합 전 staging 단계다.

## Tests

- `pytest tests/google_takeout`

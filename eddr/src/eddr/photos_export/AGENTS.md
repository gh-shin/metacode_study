# AGENTS.md - src/eddr/photos_export

## Purpose

Photos.app 라이브러리를 `osxphotos export`로 로컬 파일과 CSV 리포트로 내보내는 얇은 wrapper 계층이다. 이 폴더는 EDDR DB를 직접 수정하지 않는다.

## Read First

- `osxphotos_export.py`: export 명령 구성과 실행.
- 호출 CLI: `eddr photos export`.
- 관련 테스트: `tests/photos_export/test_osxphotos_export.py`.

## Public Surface

| Symbol | Input | Output | Notes |
|---|---|---|---|
| `build_export_command(export_dir, export_db, report_csv)` | 출력 디렉터리, osxphotos 내부 DB 경로, CSV 리포트 경로 | `list[str]` 명령 인수 | 실행하지 않고 명령만 만든다. |
| `run_export(export_dir, export_db, report_csv)` | 위와 동일 | `subprocess.CompletedProcess` | 디렉터리를 만든 뒤 `osxphotos export`를 실행한다. |

## Inputs

- `export_dir`: Photos export 파일이 놓일 디렉터리.
- `export_db`: osxphotos가 증분 export 상태를 기록하는 DB 파일.
- `report_csv`: export 결과 CSV.

## Outputs

- 파일 시스템: export 이미지 파일, `.osxphotos_export.db`, `export.csv`.
- 프로세스 결과: `CompletedProcess.returncode`, stdout/stderr.

## Side Effects

- `export_dir` 하위에 파일을 생성한다.
- 외부 바이너리 `osxphotos`를 실행한다.
- SQLite 메인 DB와 Chroma는 건드리지 않는다.

## Exceptions / Failure Modes

- `osxphotos` 미설치 또는 Photos 권한 부재 시 subprocess 실패.
- Photos.app 접근 권한은 macOS 설정에 의존한다.
- 실패 처리는 호출자 CLI가 return code와 stderr를 사용자에게 전달하는 구조다.

## Invariants

- 명령 구성은 테스트 가능해야 하므로 `build_export_command()`와 실행 함수가 분리되어 있다.
- export 결과는 이후 `eddr db load-sources`의 `--photos-export` 입력이 된다.

## Tests

- `pytest tests/photos_export/test_osxphotos_export.py`

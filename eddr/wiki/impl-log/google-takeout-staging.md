---
title: "Google Takeout 적재 파이프라인 구현"
source: ["docs/adr/0005-google-takeout-source.md", "docs/superpowers/plans/2026-06-03-google-takeout-staging.md"]
last_verified: 2026-06-04
status: fresh
confidence: high
tags: [impl-log, google-takeout, ingestion, staging]
---

# Google Takeout 적재 파이프라인 (ADR-0005 구현)

3번째 소스 `google_takeout`의 적재(staging) 파이프라인. TDD·subagent 주도로 빌드, **23 테스트 통과**. **실데이터(Task 7) 완료**: `[2011,2017)` 구간 **1,385장** 적재(2026-06-04). **02 EDA 편입(2026-06-04)**: `vision_manifest.parquet`에 1,385장 합류(local 1,737 + takeout = **3,122행**, `source` 컬럼). → [data-profile](../data-profile/eda-findings.md)

## 측정: 맥 보관함 연도 분포 (osxphotos, 이미지 8,702장)

| 연도 | 장수 | | 연도 | 장수 |
|---|---|---|---|---|
| 2012 | 2 | | 2020 | 776 |
| 2014 | 6 | | 2021 | 1,363 |
| 2015 | 19 | | 2022 | 1,536 |
| 2016 | 198 | | 2023 | 631 |
| 2017 | 585 | | 2024 | 520 |
| 2018 | 892 | | 2025 | 1,244 |
| 2019 | 655 | | 2026 | 275 |

- **맥은 2017부터 조밀**(585+), 2012–2016은 합 225장(희박). iCloud/맥 사진 생활이 사실상 2016–2017 시작.
- **확정 컷오프 C = 2017-01-01**(사용자). 수집 구간 `[2011, 2017)` = 맥 빈틈. 맥과 사실상 날짜 분리 → 교차 dedup 불필요(ADR-0005). 경계의 맥 산발 225장과 소규모 중복 가능(수용).

## 모듈 (`src/eddr/`)

- `photos_library/coverage.py` — `summarize_years`(순수)·`query_taken_dates`(osxphotos)·`print_year_table`. C 측정.
- `google_takeout/sidecar.py` — `find_sidecar`(절단 내성·`-edited` 폴백)·`parse_sidecar`(`SidecarMeta` 5필드).
- `google_takeout/walk.py` — `MediaRecord`·`build_records`(사이드카 우선·EXIF 폴백·**malformed 사이드카 skip+warn**)·`filter_by_date`.
- `google_takeout/stage.py` — `blake3_hex`·`dedup_by_content`(내부 중복)·`stage_records`(`staged/<hash>.ext` + `manifest.jsonl`).
- `google_takeout/ingest.py` — `extract_raw`·`ingest`(집계 출력)·`main`(CLI).

실행: `uv run python -m eddr.google_takeout.ingest --coverage-start 2017-01-01`

## 리뷰에서 교정한 것

- `google_media_key` 필드: deviceType를 잘못 담고 미검증 → 제거(YAGNI).
- HEIF opener 파일별 등록 → 모듈 1회.
- dedup 보관 규칙 = `source_uri` 정렬-우선(연도폴더 보장 아님) — 테스트와 일치시킴.
- `taken_at=None` silent drop → `ingest` 집계 출력(walked/no_date/out_of_range/dup/staged)으로 가시화.

## 실데이터 결과 (Task 7 · 2026-06-04)

raw **1,494** 미디어 → **staged 1,385** (manifest=staged=RETURNED 정합 PASS). 드롭: no_date 109 · out_of_range 0 · dup 0.

- 사이드카는 **39%(582/1,494)** 뿐이나 EXIF + **파일명 날짜 폴백**(commit `b9c6c93`: `YYYYMMDD_HHMMSS`·`FB_IMG_<ms>`·한국어 `수정됨`)으로 **208장 복구**(no_date 317→109). 폴백은 사이드카·EXIF 실패 시 최후 적용 → 오탐 0 확인.
- 잔여 109장 = EXIF 제거된 `_DSC*` 등 진짜 날짜 없는 파일(복구 불가, 정당 드롭).
- geo 5.2%(2011–2016 카메라 GPS 희박), description 0%(비전 단계서 생성 예정).
- macOS가 zip 자동압축해제 → `raw/`에 연도 폴더 직접(`Takeout/` 래퍼 없음, bare `2011`…`2016`). `main()`의 zip 추출 흐름과 안 맞아 `ingest()` 직접 호출로 실행. 연도 폴더는 날짜 비분리(`2011/`에 2012 사진)지만 `taken_at` 기준 필터라 정확.

## Skip되는 미디어 (RAW·영상) — 측정·보류 (2026-06-04)

walker `_MEDIA_EXT`가 잡는 **1,494**(jpg 1438+jpeg 31+png 17+gif 8) **외**, `raw/` 트리의 비대상 미디어를 실측:

- **NEF(RAW) 9개** — 전량 `raw/2016/`, JPEG 짝 0(전부 net-new), 사이드카 2/9. staged 1,385 대비 **+0.65%**. 다른 RAW 포맷(cr2/arw/dng…) 0.
- **mp4(영상) 82개** — 이미지 전용 스코프(움직임 제외) 밖. RAW보다 큰 skip 버킷.

**결정(사용자 2026-06-04): 보류.** 근거 — ①순증 9장뿐 ②NEF 추가 EXIF(렌즈·카메라)는 5-tool(날짜·GPS)에 무가치하고 2016 DSLR(`_DSC*` Nikon)은 GPS 거의 없어 실이득 ≈ "7장 날짜" ③Pillow는 NEF 디코드 불가 → `exifread`/`rawpy`/`exiftool` 신규 의존성 필요(현재 전부 미설치). staging 자체는 BLAKE3가 바이트에 걸려 디코딩 불요지만, 7장 날짜 확보엔 EXIF 리더 필수. **재고 시점**: vision 단계(⑤) 또는 RAW 비중 증가 시.

## Task 7 실데이터 watchlist (예측 — 위 결과로 대부분 해소)

- 분할 zip 동명 파일 충돌(`extractall` 순서).
- 미디어 *파일명* 절단(사이드카명 절단만 테스트됨).
- Storage Saver 재인코딩 → EXIF 소실 → `no_date_dropped` 급증 가능(집계로 확인).
- 유니코드/로캘 폴더명(`Google 포토`, `2015년 사진`) → `source_uri` 반영(manifest `ensure_ascii=False`).
- BLAKE3 이중계산: 규모 크면 최적화(현재 수용).

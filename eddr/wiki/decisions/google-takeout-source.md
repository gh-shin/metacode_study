---
title: "Google Takeout 3rd 소스 — 날짜 gap-fill"
source: ["docs/adr/0005-google-takeout-source.md"]
last_verified: 2026-06-04
status: fresh
confidence: high
tags: [data-source, google-photos, takeout, ingestion]
---

# Google Takeout 3rd 소스 (ADR-0005)

`icloud`(Photos Library)·`local`에 이은 **3번째 데이터 소스** `source = 'google_takeout'`. 목적은 "맥에 없는 사진 확보"(커버리지 빈틈).

## 핵심 결정

- **경로:** Google Photos Library API는 2025-03-31 전체 읽기 스코프 소급 삭제로 사용 불가 → **Takeout 수동 익스포트가 유일 경로**. 획득은 수동 다운로드 → `data/google_photos/raw/`.
- **범위:** `taken_at ∈ [2011, C)`. **C = 2017-01-01 확정**(osxphotos 실측: 맥은 2017부터 조밀, 2012–2016 합 225장). `2011` = 사용자 지정 하한. → [impl-log](../impl-log/google-takeout-staging.md)
- **dedup 우회:** 맥과 **날짜 분리**이므로 교차 소스 dedup·perceptual hash 불필요 → near-dup 보류([eda-scope](eda-scope.md), ADR-0004) **미변경**. Takeout 내부 중복(연도↔앨범 폴더)만 BLAKE3 정확일치로 처리.
- **메타 권위:** 시각·GPS는 JSON 사이드카(`*.supplemental-metadata.json`) 우선, EXIF 폴백.
- **이번 단계:** `staged/` + `manifest.jsonl`까지 **적재(staging)**. 메인 DB 통합은 별도.
- **EDA 편입(02 · 2026-06-04):** 02 EDA가 takeout을 3번째 소스로 독립 프로파일링(1,385장·2011–2016·GPS 4.5%)하고 `vision_manifest.parquet`에 합류(local 1,737 + takeout 1,385 = **3,122행**, `source` 컬럼 신설). cross-source dedup은 미수행(날짜분리) 유지. 03 프롬프트 EDA는 `source=="local"` 가드로 D19 결과 보존. → [data-profile](../data-profile/eda-findings.md)

## 기존 결정과의 관계

- [privacy](privacy.md) (ADR-0001): 경계는 *송신* 통제 → 외부 소스 *수신*은 위반 아님.
- [photo-identity](photo-identity.md) (ADR-0002): `source`/`source_uri`로 다중 소스 표현, Photos Library SoT 유지.
- [eda-scope](eda-scope.md) (ADR-0004): 날짜 분리로 near-dup 결정 미변경.

## 의식적 트레이드오프

`[2011, C)` 밖(맥 보관함 시작 *이후*)의 "구글 전용" 사진은 이번 범위에서 **의도적 누락**(겹침 회피). 필요 시 후속 보강.

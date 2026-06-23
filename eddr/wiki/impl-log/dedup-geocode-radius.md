---
title: "④ dedup + geocode + Daily Radius 구현"
source: ["docs/PLAN.md#4", "docs/PLAN.md#5", "docs/adr/0002-photo-identity.md"]
last_verified: 2026-06-10
status: fresh
confidence: high
tags: [impl-log, dedup, geocode, daily-radius, wizard]
---

# ④ dedup + geocode + Daily Radius 구현

## 요약

2026-06-10, 빌드 ④ 단계를 구현·실행했다. 스키마 확장(③ 잔여 테이블 해소)
→ 해시 백필 → cross-source dedup 마킹 → Nominatim geocode → Daily Radius
후보+wizard 순. 커밋: `b4d8c6f`(스키마+dedup) → `029e320`(geocode) →
`bda386a`(Daily Radius).

## 구현 내역

- **스키마 마이그레이션** (`repository.initialize`): trips·trip_countries·
  daily_radius_areas·geocode_cache 테이블 + photos에 country/city/district/
  trip_id(ON DELETE SET NULL)/duplicate_of ALTER. 멱등(베이스라인 DDL +
  컬럼 존재 검사 ALTER 목록 단일 출처). 운영 DB 사본 리허설로 11,689행·
  captions 9,383 보존 확인 후 적용.
- **dedup** (`eddr dedup backfill-hashes` / `eddr dedup mark`):
  - `dedup/hashes.py` — BLAKE3(1MiB 스트리밍, takeout staging과 동일 포맷
    교차 테스트)·dHash(imagehash, EDA 02·03 포맷, pillow-heif HEIC 등록,
    디코드 불가 None).
  - `dedup/pipeline.py` — 비어 있는 해시만 채움(기존 보존), 파일 오류는
    index_errors(stage='hash_backfill'). 마킹은 전체 재계산(멱등):
    content_hash 그룹에 소스 2+ → canonical(photos_library>local>
    google_takeout, id 사전순) 외 행 중 **canonical과 소스가 다른 행만**
    duplicate_of 기록(같은 소스 형제 미마킹 — ADR-0002).
  - `WITH ... UPDATE`는 sqlite3 드라이버 rowcount가 -1 → `changes()`로 집계.
- **geocode** (`eddr geocode run`): `geocode/nominatim.py` urllib 클라이언트
  (User-Agent, accept-language=ko, zoom=14, min_interval 1s, fetch/sleep/clock
  주입식) + `geocode/pipeline.py` 3dp 밀리도(0.001°≈110m) 양자화 캐시.
  요청은 셀 중심 좌표(캐시 정합), 주소 없는 좌표는 negative cache.
  연속 5회 실패 시 중단(aborted). 좌표순 처리로 캐시 locality 확보.
  주소 파싱: city=city|town|municipality|county, district=borough|suburb|
  city_district|district|quarter|neighbourhood|**village**(리는 district).
- **Daily Radius** (`eddr setup daily-radius`): `daily_radius/cluster.py`
  0.01° 격자 카운트 → 최대 셀부터 greedy 5km 병합 → 가중 중심·제안 반경
  (stdlib만, EDA 01 방식 계승). `daily_radius/wizard.py` 후보별 y/n/q
  대화형 확정(라벨·반경 편집, geocode 최빈 지명 표시), 확정분 전체 교체
  저장(멱등), EOF 시 무저장 중단. `--propose-only` 비대화 모드.

## 실측 (2026-06-10)

- 해시 백필: **processed 7,653** (photos_library 6,268 + takeout 1,385),
  dhash_failed 65(RAW: DNG/RW2/ORF 등 PIL 디코드 불가 — content_hash는 채움),
  errors 0. skipped_video 2,306은 대상 제외(D9).
- dedup 마킹: **165그룹·165건** — local 160 + google_takeout 5, canonical
  전부 photos_library(D4 작동). 파일명 overlap 427(EDA 02) 중 바이트 동일은
  165뿐 — 나머지는 재인코딩 추정이라 near-dup 영역(ADR-0004 보류·D8 flag).
  **마킹 local 160건 중 155건이 `2019_이탈리아` 폴더** — 노트북 05 §D-5에서
  사용자가 육안 확정한 "이탈리아 top-5 iCloud 사본 혼입"이 바로 이 중복임을
  확증. ⑦에서 duplicate_of IS NULL 필터 필수. 무결성: dangling canonical 0·
  체인(dup→dup) 0.
- geocode: 셀 2,047 예상, 1 req/s — 결과는 아래 "배치 결과" 참조.

## 배치 결과 (geocode)

2026-06-10 완주 (약 35분, 1 req/s):

- **photos_updated 7,888 / 7,888** (GPS 보유 전량) · **cells_fetched 2,047**
  (사전 예측치와 일치) · cache_hits 5,841 · **errors 0 · aborted False**.
- 사진:요청 비율 3.85:1 — 3dp 양자화 캐시가 요청을 74% 절감. negative cache 0.
- 충전율: country 100% · **city 100%(7,877/7,888)** · district 86%(6,768).
- 국가 분포(상위): 대한민국 6,303 · 아이슬란드 1,051 · 이탈리아 261 ·
  몽골 175 · 태국 69 — 사용자 여행 이력과 정합. 서울 최빈 = 강남구 730장
  (EDA 01 격자 피크 730과 일치, 교차 검증).
- 지명이 한국어(accept-language=ko)로 적재돼 ⑦ 답변·필터에 직결 —
  §D-5 실측의 지명 질의 약점(제주 0/10·일산 2/10)을 메타 필터로 보완할
  기반 확보.

## 운영 메모

- `eddr dedup mark`·`eddr geocode run`·재적재(`db load-sources`)는 어떤
  순서로 재실행해도 안전: 마킹은 전체 재계산, geocode는 country IS NULL만
  처리(캐시 히트는 요청 0), upsert는 enrichment 필드를 건드리지 않는다.
- 바다 등 주소 없는 사진은 country가 NULL로 남아 매 run 재선택되지만
  negative cache 적중이라 네트워크 요청은 없다.
- wizard는 대화형이라 **사용자가 직접 실행**해야 한다(D15):
  `.venv/bin/eddr setup daily-radius` (후보만 보려면 `--propose-only`).

## 미완료 / 후속

- wizard 실제 확정(daily_radius_areas 채우기) — 사용자 실행 대기.
- ⑥ Trip 클러스터링이 trips·trip_countries·photos.trip_id를 채움.
- ⑦ 질의 레이어: duplicate_of IS NULL 필터 + 장소 질의 GPS 무 사진 분리
  (TODO ⑦ 항목) + rank 기반 거리 설계(TODO 품질 항목).

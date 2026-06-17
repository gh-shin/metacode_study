---
title: "⑥ Trip 클러스터링 구현"
source: ["docs/PLAN.md#4", "docs/PLAN.md#5", "CONTEXT.md"]
last_verified: 2026-06-11
status: fresh
confidence: high
tags: [impl-log, trips, trip-countries, clustering, geocode]
---

# ⑥ Trip 클러스터링 구현

## 요약

2026-06-11, 빌드 ⑥ 단계를 구현·실행했다. 선행으로 geocode가 버리던 ISO
country_code를 보존·백필(사용자 결정: 한국어명 저장·하드코딩 매핑 대신
**ISO 백필** 채택, 영상은 **완전 제외**)한 뒤, 세그멘테이션 → 전체 재계산
파이프라인 → 실DB 83 trips. 커밋: `578323f`(country_code 경로) →
`c022de1`(클러스터링) → `72e8db4`(거주국 제외 + 실행).

## 구현 내역

- **geocode country_code 경로** (`eddr geocode backfill-country-code`):
  Nominatim 파서가 `address.country_code`를 **대문자 ISO 3166-1 alpha-2**로
  추출, geocode_cache에 컬럼 멱등 추가(④ 운영 DB는 ALTER 수렴). 신규 조회는
  코드를 함께 저장하고, ④가 만든 기존 셀은 재조회 백필(negative cache 제외,
  연속 5실패 중단). photos에는 저장하지 않는다 — trip 단계가 셀 단위 조회.
- **세그멘테이션** (`trips/cluster.py`, stdlib만): 일상 영역(다중) in/out →
  out 연속 run → 스팬 24h+ 필터(D14). run 분리의 **주 신호는 복귀**(in 사진
  등장)이고 사진 공백 임계는 안전장치 — 기본 24h였다면 "여행 중 하루 무촬영"
  (2박3일 33h 공백)이 가짜 분리돼 **72h로 설정**(TDD가 적발, 민감도는 D14
  심화에서). 다국가 1 trip은 복귀 기반 분리로 자연 보장.
- **재계산 파이프라인** (`trips/pipeline.py`, `eddr trips recompute`):
  전체 재계산 멱등(리셋 → 재배정). 결정적 id `trip_<YYYYMMDD>_<NN>`,
  이름 자동 생성(해외=최빈 외국 국가명·국내=최빈 city, "{지명} 여행 YYYY-MM",
  지명 없으면 "여행 YYYY-MM"). 경계는 naive UTC `YYYY-MM-DD HH:MM:SS`.
- **배정·전이** (`assign_trip_by_timerange`): 기간 내 사진 일괄 UPDATE —
  세그먼트가 복귀에서 끊기므로 기간 내 GPS 사진은 전부 run 소속이고,
  **no-GPS도 시간만 맞으면 배정**(PLAN §8). 영상 제외. `caption_done`만
  `trip_assigned` 전이(타 status는 trip_id만 받고 체크포인트 보존).
  taken_at 포맷 혼재(aware/naive, local 806건 naive)는 SQLite `datetime()`
  정규화로 흡수 — Python 측도 aware→UTC naive 변환으로 동일 절삭.
- **trip_countries**: 사진 좌표 양자화 셀 → 캐시 ISO 코드 집합.
  **해외 trip은 거주국(KR) 제외** — 출국·귀국 공항 사진이 묶여도 거주국은
  방문국이 아니다(CONTEXT.md "인천→로마→뮌헨→인천 = trip-country 2개").
  국내 trip은 KR 유지. 실DB 검증에서 위반 발견 후 교정(`72e8db4`).

## 실측 (2026-06-11)

- 백필: **2,047/2,047셀 · 오류 0 · 약 35분**. 9개국 — KR 1,674 · IS 181 ·
  IT 91 · MN 54 · TH 27 · CN 9 · GB 5 · DE 4 · NL 2.
- recompute: **83 trips · 배정 3,760**(no-GPS 758 포함 — EDA "no-GPS 773장
  배정" 과제의 1차 해소). photo_count 합 3,759 = 배정 − dup 1(이탈리아 사본
  160건은 taken_at NULL이라 자연 제외 — canonical은 배정됨, 무해).
  0.7초 완주. 재실행 동일 결과(멱등 확인).
- 기간 분포: 최단 1.01일 · 평균 2.8일 · 최장 14.7일.
- 상위: 아이슬란드 2022-09(530장, **DE·GB·IS**) · 몽골 2018-07(448, CN·MN) ·
  아이슬란드 2025-09(384, GB·IS·NL) · 이탈리아 2019-06(278, IT) ·
  서귀포시 2022-06(177, KR). 다국가 1 trip(환승 경유 포함) 작동.
- EDA 교차: 이탈리아 trip이 EDA 01 최장 trip(2019-06-29~07-12, 264장)과
  **경계 일치**(264→278은 입력 기준 차이). 44→83 증가는 반경 축소
  (50km 단일 → 5~6.6km 4영역)의 예상된 결과 — 서울 내 타지역·근교 1박이
  추가 인정("서울특별시 여행 2022-07" 등).
- R1 기준 시나리오 즉답 가능: 몽골 **2018-07** · 이탈리아 **2019-06**.

## 운영 메모

- `eddr trips recompute`는 언제든 재실행 안전(전체 재계산 멱등). 파라미터
  `--min-duration-hours 24` `--max-gap-hours 72`.
- 신규 사진 geocode 시 country_code가 함께 캐시되므로 백필은 1회성.
- daily_radius_areas를 wizard로 바꾸면 recompute 재실행으로 trip이 따라온다.

## 미완료 / 후속

- **1박2일 < 24h 스팬 누락 가능**: D14 정의(24h+)를 그대로 구현 — 토 14시
  출발~일 12시 복귀(22h)는 미인정. 골든셋(⑧)에서 실누락 확인 후 조정 검토.
- **연속 이틀 낮 외출 가짜 trip 가능**: 밤 집 사진이 전혀 없으면 이틀 외출이
  스팬 24h+로 합쳐질 수 있음 — 일상 사진 밀도가 높아 실위험 낮음, D14 심화
  (파라미터 민감도)에서 검토.
- ⑦ 질의 레이어: list_trips/get_trip 데이터 준비 완료. dedup 필터·GPS 무
  사진 분리와 함께 설계(TODO ⑦).

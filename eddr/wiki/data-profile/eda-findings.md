---
title: "EDA 실측 핵심 수치"
source: ["docs/01_eda_findings.md", "notebooks/01_eda.ipynb", "notebooks/02_full_dataset_eda.ipynb", "notebooks/03_vision_caption_eda.ipynb", "notebooks/04_day_geocaption_eda.ipynb"]
last_verified: 2026-06-04
status: fresh
confidence: high
tags: [eda, data-profile, metrics, vision]
---

# EDA 실측 핵심 수치

> 출처: `docs/01_eda_findings.md` (최초 2026-05-31, 풀데이터셋 §7 추가 2026-06-03)
> 범위: 메타데이터 전용 검증(01) + 풀데이터셋 픽셀/정합성 EDA(02; 3소스 icloud·local·**google_takeout**) + Vision 캡션 프롬프트 EDA(03) + day-place 장소추정 캡션 보강 EDA(04).

## 핵심 수치 한눈에

| 항목 | 수치 | 세션 |
|------|------|------|
| 총 iCloud assets | **9,054** (이미지 8,701 + 동영상 353; 01: 9,047 → +7 live) | 02 |
| 로컬 분석가능 이미지 | **1,738** | 02 |
| 보정 총 풋프린트 (iCloud ∪ icloud_new) | **≤10,365** (상한, 파일명 기반) | 02 |
| overlap (파일명 매칭) | **427장 (24.6%)** | 02 |
| icloud_new (로컬 전용) | **1,311장 (75.4%)** | 02 |
| google_takeout staged (3번째 소스) | **1,385** (2011–2016 gap-fill, GPS 4.5%·62장) | 02 |
| 보정 풋프린트 (+takeout) | **11,750** (10,365 + 1,385; dedup 미수행·날짜분리) | 02 |
| vision_manifest 행수 | **3,122** (local 1,737 + takeout 1,385, `source` 컬럼) | 02 |
| 로컬 EXIF GPS 보유율 | **0.1% (사실상 0)** | 02 |
| 로컬 EXIF date 보유율 | **46.4%** | 02 |
| 실 near-dup (dHash Hamming≤1) | **919쌍 (0.061%)** | 02 |
| BLAKE3 정확중복 | **14파일** | 02 |
| 해상도 중앙값 | **1.7MP** (bimodal, png 집단 영향) | 02 |
| INDEXABLE (D18 필터 후) | **8,574 (94.8%)** | 01 |
| GPS 좌표 보유 (INDEXABLE 중) | **~91%** (7,801장) | 01 |
| `taken_at` 유효 | **100%** (미래 날짜 0, 1970 sentinel 0) | 01 |
| Named person | 1명, INDEXABLE의 **12.3%** (~1,050장) | 01 |
| Trip 후보 (자동 세그멘테이션) | **~44개** | 01 |
| GPS 없는 dated 사진 | **773장** (INDEXABLE의 9%) | 01 |
| 캡션 처리량 (e2b / 26b) | **8.3s / 18.6s** per img (워밍) | 03 |
| 캡션 best 프롬프트 | **P3_hybrid** (서술+키워드) | 03 |
| D19 한국어질의 recall@10 (P3) | **0.70 → PASS** | 03 |
| day-place 보강 recall@10 (base/공격/보수) | **0.6 / 0.6 / 0.5** (제주·일산 0.00) | 04 |
| day-place 보강 결론 | **순효과 미미·환각 발목 → v1 보류** | 04 |

## D18 제외 Waterfall

| 단계 | 잔여 | 제외 |
|------|------|------|
| 전체 assets | 9,047 | — |
| − 동영상 | 8,694 | 353 |
| − hidden | 8,694 | 0 |
| − burst non-keeper | 8,692 | 2 |
| − screenshot | 8,584 | 108 |
| − document scan | 8,584 | 0 |
| − <300px | 8,574 | 10 |
| **INDEXABLE** | **8,574 (94.8%)** | |

## 가정별 검증 결과

| 가정 | 판정 | 메모 |
|------|------|------|
| D18/D9 INDEXABLE 비율 | VALIDATED | 제외 규칙 조정 불필요 |
| D14/D15 GPS 커버리지 | VALIDATED | 2021년 이후 97–98%로 안정 |
| D22 taken_at 유효·recent-first | VALIDATED | 최근 12개월 1,113장 = 1차 배치 적정 |
| D14 Trip 후보 feasibility | VALIDATED | 44개 자동 검출, 세그먼트 알고리즘 동작 확인 |
| D15 Daily Radius 군집 | VALIDATED | 서울 강남·서초 최대 밀집(단일 격자 730장), 비서울 최대 아이슬란드(~180장) |
| D14 no-GPS dated | 관찰 | 773장(9%), 시간근접 배정 가능성은 별도 세션 |

## 주요 결정 (ADR-0004 촉발)

- **near-dup(D8) v1 보류**: 93쌍 전부 export artifact(Hamming 0). 라이브러리 실제 near-dup율 미측정 → v1은 중복 허용. **[02 업데이트]** 실측 919쌍(0.061%) — D8 재검토 ADR flag(결정은 사용자).
- **Person 질의(D10) v1 폐기**: named person 1명, INDEXABLE 12.3%만 커버 → R2 person 질의 recall 구조적 불가. 데이터 적재는 유지.

## 범위 밖 (별도 세션)

- D14 Trip 심화: 전체 44개 프로파일, 파라미터 민감도, no-GPS 773장 배정
- D12 로컬파일/iCloud EDA: ~~로컬 2.7%, 픽셀 기반 EDA~~ → **완료(02)**: icloud_new 75.4% / overlap 24.6%
- ~~D19/D20 Vision~~ → **완료(03)**: D19 PASS(recall@10 0.70), best 프롬프트 P3_hybrid. 지명질의 약점→GPS/trip 보완. image-embedding leg(D20 image kind)는 비범위.
- ~~D20 캡션경로(day-place 보강)~~ → **완료(04)**: 26b multi-image coarse 지명 보강. 순효과 미미(recall@10 0.6 불변)·환각 발목(부산→Jeju) → **v1 보류**, 지명은 D14 메타. image leg(D20 image kind)는 여전히 비범위.
- ~~D8 실제 near-dup 측정~~ → **완료(02)**: 919쌍(0.061%), ADR flag(결정은 사용자)
- ~~google_takeout 3번째 소스 EDA 편입~~ → **완료(02, ADR-0005)**: 1,385장 독립 프로파일 + vision_manifest 합류(3,122행). 날짜분리[2011,2017)라 cross-source dedup 미수행. 03(프롬프트 EDA)은 local 전용 가드로 D19 보존
- icloud_new timestamp 매칭: 파일명 기반 상한(10,365) 정밀화

결과 결정 상세는 `../decisions/eda-scope.md` 참조.

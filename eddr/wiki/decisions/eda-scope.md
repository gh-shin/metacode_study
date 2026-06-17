---
title: "EDA 후속 스코프 결정 (D8 보류·D10 폐기)"
source: ["docs/adr/0004-eda-driven-scope-decisions.md", "docs/01_eda_findings.md"]
last_verified: 2026-06-04
status: fresh
confidence: high
tags: [eda, scope, near-dup, person]
---

## 배경

구현 착수 전 실제 Photos Library(9,047 assets)로 설계 가정을 검증하는 EDA(`notebooks/01_eda.ipynb`)를 실행했다. 메타데이터 기반 가정 6건 중 5건 VALIDATED, 1건 관찰. 이 중 두 측정 결과가 v1 범위 변경을 요구했다.

## D8 — near-duplicate 처리 v1 보류

**측정 사실**: 디스크 샘플의 near-dup 93쌍이 전부 export 과정이 만든 `(1)` 복사본 아티팩트였다(BLAKE3·dHash 모두 동일, Hamming distance 0). 라이브러리의 **실제 near-dup율은 미측정** 상태(01 시점).

**[02 보강 — 2026-06-04]** 02 EDA가 사용자 로컬 아카이브 1,738장으로 처음 실측 → **Hamming≤1 919쌍(전체 쌍의 0.061%)**, BLAKE3 정확중복 14파일, cross-folder 334쌍(36.3%, 여행 백업 패턴). **0.061%는 낮아 v1 near-dup 보류 유지가 타당**함을 확인. cutoff·처리 여부는 인덱싱 후 재튜닝 대상으로 남음. → findings §7.5

추가로, INDEXABLE(8,574장) 중 로컬 파일 보유는 **2.7%(232장)**뿐이고 나머지는 iCloud-only여서, 전체 해싱 기반 실측 자체가 별도 세션의 선행 작업을 필요로 한다.

**결정**: v1에서 near-dup 처리를 보류하고 중복을 허용. `near_duplicate_group_id` 등 dedup 산출물은 v1 미생성(또는 best-effort). 실제 문제(검색·그리드 중복 노출)가 발생하면 그때 대응. dedup 튜닝은 로컬파일 기반 실측이 가능해진 뒤 별도 세션에서 결정.

## D10 — Person 기반 질의(R2) v1 폐기

**측정 사실**: named person이 라이브러리 전체에 **단 1명**, INDEXABLE의 **12.3%(약 1,050장)**에만 존재한다. R2("누구랑") person 질의의 recall이 데이터 차원에서 구조적으로 불가능한 상태.

**결정**: person 기반 질의를 v1 범위에서 폐기. 인물 라벨이 충분히 축적되면 재검토.

**중요**: person **데이터 적재**(`persons`/`photo_persons` 테이블, `search_photos`의 `persons` 필터)는 유지. **질의 기능**만 v1에서 제외. 골든셋 R2(3문항) 분포는 사용자가 재검토 필요.

## 공통 원칙

두 결정 모두 **v1 한정**이며 영구 결정이 아니다. 데이터 여건 변화 시(인물 라벨 증가, 로컬파일 기반 실측 가능) 다시 열어 검토한다.

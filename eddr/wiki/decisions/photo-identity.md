---
title: "Photo 정체성"
source: ["docs/adr/0002-photo-identity.md", "docs/PLAN.md#D16"]
last_verified: 2026-06-01
status: fresh
confidence: high
tags: [photo, identity, dedup]
---

## 결정 요약

EDDR `photos` 테이블의 1행이 무엇을 나타내는지 정의한 결정. Photos.app asset 단위를 정체성의 SoT로 삼는다.

## 핵심 규칙

- **Photos.app asset 1개 = EDDR `photos` 1행**
- `source_uri` = Photos UUID (Photos Library 사진) 또는 로컬 절대경로 (로컬 폴더 파일)
- **원본 + 보정본 = 1 photo**: variant 정보는 v1에서 보존하지 않음. Photos가 노출하는 default representation만 사용.
- **Burst는 keeper(`burst_selected`)만** 인덱싱.
- **Live Photo는 정지 이미지만** 사용 (영상 파트 제외, D9).
- iCloud Shared Library asset도 포함 (owner 무관).
- 로컬 폴더 파일은 별개 `photos` 행.

## dedup 규칙 (cross-source 중복만 처리)

- 로컬 파일의 BLAKE3가 Photos asset과 일치 → 로컬 skip (Photos 우선, D4).
- BLAKE3 다르지만 dHash 가까움 → 양쪽 인덱싱하되 `near_duplicate_group_id`로 묶음. UI는 그룹당 1장만 노출.
  - **단, near-dup 처리는 ADR-0004로 v1 보류** — 현재 중복 허용.

## 왜 이 결정인가

- 사용자 인식("Photos.app에서 보는 그 사진")과 EDDR row가 1:1 대응 → query 답변이 자연스러움.
- 같은 장면이 답변에 여러 번 등장하지 않음.
- Photos.app이 이미 계산한 엔티티 경계를 그대로 활용 → EDDR 코드 단순화.

## 주요 트레이드오프

- 보정본의 캡션/임베딩을 별도 생성하지 않음 → "필터 강한 사진" 같은 query 정확도 저하 가능 (v1에서는 이런 query를 하지 않는다고 가정).
- Photos.app person/asset UUID에 의존 → Photos.app 데이터 모델 변경 시 EDDR도 영향.

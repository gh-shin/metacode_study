# ADR-0002: Photo Identity — Photos.app asset이 정체성의 source of truth

## Status

Accepted (2026-05-29)

## Context

Photos Library는 같은 "사진"에 대해 여러 binary representation을 생성한다:

- 원본 + 사용자가 보정한 버전 (asset 1개, file 2개, **서로 다른 BLAKE3**)
- Burst sequence (사용자가 keeper 1장 지정, 나머지는 backup)
- iCloud Shared Library (가족이 추가한 사진)
- Live Photo (정지 이미지 + 3초 영상)

또한 사용자가 같은 사진을 외부 폴더에 HEIC→JPG 등으로 export해 둔 경우, 다른 binary지만 거의 같은 시각 내용을 갖는 파일이 별도로 존재할 수 있다.

EDDR `photos` row 1개가 무엇과 1:1 대응되는지가 정해지지 않으면, 같은 장면이 답변에 여러 번 등장하거나 dedup 규칙이 일관되지 않게 된다.

검토한 옵션:

- (a) Binary identity (BLAKE3 unique): 원본·보정본·burst 전부 별개 row → 사용자 인식 ("같은 사진")과 어긋남
- (b) Photos asset identity (Photos UUID): 원본+보정본 = 1 row, burst keeper만 = 1 row — **채택**
- (c) Logical photo cluster (자체 dHash 클러스터링): v1 over-engineering

## Decision

- **Photos Library asset 1개 = EDDR `photos` 1행**. `source_uri` = Photos UUID.
- 원본/보정본의 variant 정보는 v1에 보존 안 함 (Photos가 노출하는 default representation만 사용).
- Burst는 keeper(`burst_selected`)만 indexed.
- Live Photo는 정지 이미지만 사용 (PLAN.md §D9).
- iCloud Shared Library asset도 포함 (owner 무관).
- 로컬 폴더 사진은 별개 `photos` 행. `source_uri` = 절대 경로.

**dedup은 cross-source 중복만 처리:**

- 로컬 파일의 BLAKE3가 Photos asset 어느 것과 일치 → 로컬 skip (Photos 우선, D4).
- BLAKE3 다르지만 dHash 가까움 → 양쪽 인덱싱하되 `near_duplicate_group_id`로 묶음 (UI는 그룹 당 1장만 노출).

## Consequences

**Positive:**

- 사용자 인식 ("Photos.app에서 보는 그 사진")과 EDDR row가 1:1 → query 답 자연스러움.
- 같은 장면이 답에 여러 번 등장하지 않음.
- Photos.app이 이미 계산한 엔티티 경계를 그대로 받음 → EDDR 코드 단순.
- D4 ("Photos Library가 source of truth")와 일관.

**Negative:**

- 보정본의 caption/embedding을 따로 생성 안 함 → "필터 강한 사진" 같은 query 정확도 ↓ (v1엔 이런 query 안 한다고 가정).
- Photos.app person/asset UUID에 의존 — Photos.app 데이터 모델 변경 시 EDDR도 영향.
- iCloud Shared Library 사진이 가족 owner여도 포함 — 사용자가 "내 사진" 인식에 맞춤 (v2에서 owner filter 토글 후보).

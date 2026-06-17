# ADR-0001: Privacy Boundary — 외부 LLM API로 보내는 데이터의 경계

## Status

Accepted (2026-05-29)

## Context

EDDR은 사용자 사진 메타·캡션을 외부 LLM API(Anthropic Claude 등)에 query 답변 생성용으로 전달한다. PLAN.md §D6은 "이미지 바이너리는 절대 미전송, 텍스트는 OK"로 큰 줄기를 정했지만 텍스트의 입자(granularity)가 정의되지 않았다.

대표적 우려:

- 정밀 좌표(`latitude`, `longitude`) → 사용자 집·실내 주소 식별 가능
- `person.name` (특히 "엄마", "할머니" 같은 관계어) → 가족 구조 노출
- Photos.app hidden 사진 → 사용자가 명시적으로 숨긴 의도 위반
- EXIF의 camera serial 같은 PII

검토한 옵션:

- (a) D6 strict: 모든 텍스트 전송 — 정밀 좌표·관계어 노출
- (b) 좌표만 도시 단위 — 가족명 노출
- (c) (b) + Photos hidden 인덱싱 제외 — **채택**
- (d) (c) + `person.name` 익명화 — query 정확도 ↓ (관계어 검색 불가)

## Decision

**LLM에 전송 가능:**

- `taken_at` (시간)
- reverse geocode 결과 (`country`, `city`, `district`)
- `person.name` (named persons only, hidden person 제외)
- caption text 전체
- 기본 EXIF (`width`, `height`, `camera_make`, `camera_model`)
- trip 메타 (id, name, dates, top persons)

**LLM에 절대 미전송:**

- 정밀 좌표(`latitude`, `longitude`) — EDDR 로컬 거리 계산에는 사용
- raw image 바이너리 (D6)
- Photos.app hidden 사진 → **인덱싱 단계부터 제외** (DB에 없음)
- camera serial 등 PII EXIF

**구현 측면**: LLM tool 응답 schema가 이 정책을 자동 강제한다 (ADR-0003 참고). tool 함수는 절대 정밀 좌표·PII를 응답에 포함하지 않음.

## Consequences

**Positive:**

- 사용자 집 주소가 외부 API 로그에 남지 않음.
- Hidden 사진 의도 자동 보호.
- Tool surface 응답 schema가 단순화됨 (lat/lng 컬럼 없음).

**Negative:**

- "내 집 근처 카페" 같은 query는 EDDR 로컬에서 거리 계산 후 candidate 사진만 LLM에 넘기는 우회가 필요.
- `person.name`이 LLM에 전송됨 → 사용자 본인 도구라는 가정에 의존. v2에서 multi-user 또는 cloud 배포 시 재검토 필요.
- Hidden 사진은 EDDR이 영영 모름. 사용자가 hide를 풀면 다음 `eddr update`에서 신규 사진으로 잡힘 (의도된 동작).

# ADR-0003: LLM Tool Surface — freeform SQL 대신 structured tools

## Status

Accepted (2026-05-29)

## Context

EDDR의 query 답변은 외부 LLM(Claude)이 EDDR DB에 tool use로 접근하는 방식. 초기 계획(PLAN.md §6)은 다음 3종이었다:

- `sql_query(sql)` — 임의 SQL
- `semantic_search(query, k)` — 임베딩 검색
- `get_caption(photo_id)` — 캡션 조회

`sql_query(sql)`의 우려:

- LLM hallucinated SQL이 destructive (DROP TABLE 등) — read-only connection으로 일부 완화 가능하나 row 수 폭발은 막기 어려움
- Schema 변경 시 LLM prompt를 매번 업데이트 필요
- ADR-0001 privacy boundary 강제 어려움 — LLM이 `SELECT latitude FROM photos`를 쓰면?
- 응답 row 수 무제한 → context overflow 가능

검토한 옵션:

- (A) Freeform SQL (원안)
- (B) Structured tools (5종) — **채택**
- (C) Hybrid (structured + SQL escape hatch)

## Decision

v1 tool surface는 다음 5종으로 한정한다. **freeform SQL 없음.**

```
search_photos(
  date_range?: {from, to},
  countries?: [str],
  cities?: [str],
  persons?: [str],
  caption_match?: str,
  trip_id?: str,
  limit: int = 20
) → [PhotoSummary]

semantic_search_photos(
  query: str,
  k: int = 20,
  filters?: { ...search_photos와 동일 }
) → [PhotoSummary with score]

list_trips(
  countries?: [str],
  date_range?: {from, to},
  persons?: [str],
  limit: int = 10
) → [TripSummary]

get_trip(trip_id: str) → TripDetail
get_photo(photo_id: str) → PhotoDetail
```

응답 schema 원칙:

- 정밀 좌표(`latitude`, `longitude`) 절대 미포함 — ADR-0001 자동 강제
- camera serial 등 PII EXIF 미포함
- 모든 list 응답은 `limit` 강제 — context overflow 차단

**새 query 패턴은 골든셋 검증 결과로 필요시 tool 추가** (YAGNI, over-engineering 회피).

## Consequences

**Positive:**

- ADR-0001 privacy boundary 자동 강제 — tool 응답 스키마에 노출 컬럼이 정해져 있음.
- LLM hallucinated SQL 위험 제거.
- Schema 변경 시 LLM prompt 그대로 — tool 응답 schema만 결정.
- Context overflow 방지 (limit).
- Trip이 first-class tool로 노출 (D11과 일관).

**Negative:**

- 복잡한 ad-hoc query (예: "월별 사진 통계", "최다 동행자 top-5")는 v1에서 답 못 줄 수 있음. → 골든셋이 이 케이스를 다루지 않게 작성.
- 새 query 패턴 추가 시 tool 추가 필요. → "그때 다시 고민" YAGNI로 수용.
- LLM이 multi-tool reasoning 해야 하는 경우 latency·token 비용 ↑.

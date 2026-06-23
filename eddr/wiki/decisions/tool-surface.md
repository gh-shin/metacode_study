---
title: "LLM Tool Surface (5개) — superseded"
source: ["docs/adr/0003-llm-tool-surface.md", "docs/adr/0009-map-local-search.md", "docs/PLAN.md#D21"]
last_verified: 2026-06-11
status: archived
confidence: high
tags: [llm-tool, api, yagni, superseded]
---

> ⚠️ **ADR-0009(2026-06-11)로 superseded** — 채팅·외부 LLM 폐기로 "LLM tool surface" 개념 자체가 소멸했다. `QueryService`는 **내부 검색 서비스**로 존속하며(privacy 스키마·limit 강제 등 구현 자산 계승, 시그니처 변경 자유), 잔존하던 `persons` 명세 불일치도 함께 종결. 현행 결정은 [[local-search]](local-search.md). 아래는 역사 기록.

## 결정 요약

v1 LLM tool surface를 5개 structured tool로 한정하고, freeform SQL을 배제한 결정. 임의 SQL(`sql_query`)은 hallucinated destructive query 위험, privacy boundary 강제 불가, context overflow 위험 등의 이유로 채택하지 않았다.

## 5개 Tool 명세

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
```
날짜·위치·인물·caption·trip 조건으로 사진을 필터링해 목록 반환.

```
semantic_search_photos(
  query: str,
  k: int = 20,
  filters?: { ...search_photos와 동일 }
) → [PhotoSummary with score]
```
임베딩 벡터 유사도 검색. 의미 기반 질의("결혼식 사진", "케이크 먹은 사진" 등).

```
list_trips(
  countries?: [str],
  date_range?: {from, to},
  persons?: [str],
  limit: int = 10
) → [TripSummary]
```
조건에 맞는 trip 목록 반환.

```
get_trip(trip_id: str) → TripDetail
```
trip 상세 정보(사진 수, 기간, 국가 등) 조회.

```
get_photo(photo_id: str) → PhotoDetail
```
단일 사진 상세 정보 조회.

## 응답 Schema 원칙

- **정밀 좌표(`latitude`, `longitude`) 절대 미포함** — ADR-0001 privacy boundary 자동 강제.
- **camera serial 등 PII EXIF 미포함**.
- **모든 list 응답은 `limit` 강제** — context overflow 차단.

## YAGNI 원칙

새 query 패턴은 골든셋 검증 결과가 실제로 요구할 때만 tool을 추가한다. 복잡한 ad-hoc query("월별 통계", "최다 동행자 top-5")는 v1에서 답하지 않는 것을 허용하며, 골든셋도 이 케이스를 다루지 않도록 작성한다.

## 주요 트레이드오프

- Privacy boundary를 tool 응답 schema가 자동 강제 → hallucinated SQL이 `SELECT latitude FROM photos` 같은 우회를 시도해도 데이터가 나가지 않음.
- multi-tool reasoning이 필요한 query는 latency·token 비용 증가.

---
title: "지도 중심 로컬 검색 전환 (D26)"
source: ["docs/adr/0009-map-local-search.md", "docs/prd.md", "docs/scenario.md"]
last_verified: 2026-06-11
status: fresh
confidence: high
tags: [search, map, local-llm, privacy, decisions]
---

# 지도 중심 로컬 검색 전환 (D26, ADR-0009)

채팅 UX 폐기 → 지도 홈 + 검색 전용. **supersedes [[tool-surface]](tool-surface.md)(ADR-0003), amends [[privacy]](privacy.md)(ADR-0001).** 사용자 확정 8건(D26-①~⑧)은 `docs/prd.md` §4.

## 되돌리기 비싼 결정 6건 (ADR-0009)

| # | 결정 | 요지 |
|---|---|---|
| 1 | 대화형 UX 폐기 | 질의 출력은 사진(날짜 lane)뿐 — 텍스트 답변·후속 맥락 없음. 골든셋은 검색 결과 자동 채점으로 재정의 |
| 2 | 런타임 LLM 완전 로컬화 | 해석 `gemma4:e2b`(캡션 모델 재사용) + 임베딩 `qwen3-embedding:8b`(색인 동일 — 교체 불가). anthropic SDK·API 키 제거. 외부 네트워크 의존 = 타일 + Nominatim 2개 |
| 3 | 좌표 로컬 노출 허용 | 금지의 본질 = "외부 LLM 전송". 내 서버→내 브라우저는 허용(지도 렌더) — ADR-0008 가드가 경계 |
| 4 | 수동 위치 = DB 직접 갱신 | `photos.latitude/longitude` + `location_source='manual'`(EXIF 유래=NULL). 원본 파일 비파괴. 주소는 기존 reverse 경로 통일 |
| 5 | 지도 스택 | MapLibre GL JS + OpenFreeMap(키 불필요) — 클러스터·flyTo 내장, PMTiles 오프라인 확장 경로 |
| 6 | 날짜 = KST 달력일 | taken_at을 KST(+09:00) aware ISO로 백필(원본 보존). 해외 사진의 현지일 어긋남 수용 |

## 검색 파이프라인 (M3 목표)

```
질의 → QueryExtractor(gemma4:e2b, structured output: keywords_en·날짜·지역 — 실패 시 임베딩-only 폴백)
     → 지역명→trips 매칭(trip_ids — GPS 무 사진 포함)
     → QueryService.semantic_search_photos(임베딩 leg + BM25 leg + note leg, RRF 융합)
     → KST 날짜 그룹핑·관련도순 lane + 지도 하이라이트
```

- 임베딩 질의는 원문 한국어(instruct prefix — 검증 자산), keywords_en만 영어(영어 캡션 FTS porter용).
- 장소 필터: `(country LIKE … OR city LIKE … OR trip_id IN …)` 단일 OR 그룹.

## 마일스톤·게이트 (prd v2 §7)

M0 문서 → M1 KST 정규화 → M2 지도 셸+Tailscale HTTPS(폰 E2E) → M3 로컬 검색+채팅 일괄 삭제(골든 G06 제외 8/9↑) → M4 수동 지오코딩(G06 → 10/10) → M5 메모(회귀 10/10) → M6 운영(선택).

## 주요 트레이드오프

- 해석 품질 Claude → gemma4:e2b 하락 가능 — bench_extract 선검증·폴백·해석 칩·골든 자동채점 회귀로 흡수.
- 후속 질문 맥락 상실 — 의도된 단순화.
- 타일 좌표·장소 검색어의 외부 노출 — 최소 입자·서버 프록시 일원화로 수용(ADR-0009 §3).

---
title: "질의 흐름 — 로컬 검색 파이프라인 (D26)"
source: ["docs/PLAN.md#6", "docs/adr/0009-map-local-search.md", "docs/prd.md", "docs/01_eda_findings.md#8"]
last_verified: 2026-06-11
status: fresh
confidence: high
tags: [query, search, local-llm, architecture]
---

# 질의 흐름 — 로컬 검색 파이프라인 (D26)

권위: [PLAN §6](../../docs/PLAN.md)(v2 갱신)·[prd v2 §6-c](../../docs/prd.md). **채팅·Claude tool-use 루프는 ADR-0009로 폐기** — 구 흐름(Gradio→Claude→5 tools)은 M3 삭제 전까지 코드에 잔존하며, 역사 기록은 [[query-service]](../impl-log/query-service.md)·[[tool-surface]](../decisions/tool-surface.md)(archived).

## 흐름 (M3 목표)

```
사용자 한국어 질의 (지도 홈 하단 검색창)
        │ POST /api/search
        ▼
QueryExtractor (src/eddr/query/extract.py — gemma4:e2b, ollama structured output, temp 0)
  ├─ 프롬프트: 오늘 날짜(KST) 주입 + few-shot 4(시기/의미/복합/상대날짜)
  ├─ 출력: {keywords_en[], date_from, date_to, countries[], cities[]}  ※ 지명은 한국어
  └─ 폴백: JSON 실패 → 1회 재시도 → 임베딩-only(fallback=true)
        │
        ├─ 지역명 → trips 조회 → trip_ids (GPS 무 사진 우회 — 구 Claude의 list_trips 역할)
        ▼
QueryService.semantic_search_photos (src/eddr/query/tools.py — 내부 검색 서비스)
  ├─ 임베딩 leg: qwen3-embedding:8b + instruct prefix(원문 한국어 — recall +8.8% 검증 자산)
  ├─ lexical leg: FTS5 BM25 (영어 캡션 ← keywords_en)
  ├─ note leg(M5): Chroma eddr_note_text_v1 (사용자 메모)
  └─ RRF 융합(_rrf_fuse 가변 인자) + adaptive over-fetch(×5) + 노출 필터(영상·dup 제외)
        ▼
서버 그룹핑: KST 달력일별, 그룹 정렬 = 그룹 내 최고 rank(관련도순, D26-⑦)
        ▼
{interpretation(해석 칩·fallback), groups[+좌표]} — 텍스트 답변 없음. 지도 하이라이트 + flyTo
```

## 검색 전략 — 질의 유형별 leg 기여 (03 EDA 계승)

| 질의 유형 | 주 신호 | 비고 |
|---|---|---|
| *무엇* (이벤트·객체·음식) | 임베딩 leg (+keywords_en BM25) | 캡션검색 recall@10 0.70 (D19 PASS) |
| *어디서* (고유지명) | countries/cities 필터 **OR trip_ids** | 영어 캡션의 한글 지명 약점 → 메타 필터. GPS 무 사진은 trip_ids가 회수. M4 수동 지오코딩·M5 메모가 커버리지 확대 |
| *언제* ("작년 여름") | 추출된 date_from/to | gemma 상대날짜 해석 — bench_extract로 선검증. "하루"=KST 달력일(ADR-0009 §6) |

- 구 시스템에선 이 분기를 Claude 시스템 프롬프트가 수행 — D26은 **추출기 + 단일 융합 검색**으로 환원(분기 자체가 RRF 가중으로 흡수).
- rank 중심·distance 절대값 컷오프 금지(노트북 05 §D-4)는 그대로 유효.

## 오류 경로

| 상황 | 동작 |
|---|---|
| ollama 미기동 | 503 + 한국어 안내 토스트("ollama serve 후 재시도"). `/api/status`의 ollama 헬스(M6)로 사전 가시화 |
| 추출 JSON 실패 | 1회 재시도 → 임베딩-only 폴백, 해석 칩에 fallback 표시 |
| 결과 0건 | 빈 lane 안내 + 해석 칩 유지(오추출 의심 시 사용자가 재질의) |

## Privacy (ADR-0001 + ADR-0009)

런타임 외부 LLM 호출 0회. 좌표는 내 서버→내 브라우저만(지도 렌더). 외부 전송은 타일 좌표(OpenFreeMap)·장소 검색어(Nominatim 프록시, M4)뿐. 이미지 바이너리·hidden·절대경로 미노출 불변 → [[privacy]](../decisions/privacy.md).

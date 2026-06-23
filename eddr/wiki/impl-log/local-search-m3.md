---
title: "D26 M3 — 로컬 검색 전환 + 채팅 일괄 삭제"
source: ["docs/prd.md", "docs/scenario.md", "docs/adr/0009-map-local-search.md"]
last_verified: 2026-06-21
status: fresh
confidence: high
tags: [impl-log, search, local-llm, deletion, golden]
---

# D26 M3 — 로컬 검색 전환 + 채팅 일괄 삭제 (2026-06-12)

S2(자연어 검색 → 날짜 lane) 구현 + **런타임 외부 LLM 0회 달성**(ADR-0009 §2). commits: 추출 게이트 `866b720`·`b52e069`·`155277d` → 본구현 `0ca9ddd`·`7533de3`·`2bd631a`·`04d515e` → 리뷰 수정 `d6a2212`.

## 추출 게이트 (선행)

`QueryExtractor`(extract.py — gemma4:e2b structured output·temp 0·오늘 KST 주입·few-shot 6): 벤치 v1(17/20) → **프롬프트 v3**(연도 표지 없으면 날짜 금지·N년 전=해당 연도·주말 산술·지명 키워드 금지) → G05 과추출·V06 해소. 잔여 "대한민국" 유추는 **코드 후처리**(`_drop_redundant_home_country` — 국내 도시 동반 시 거주국 드롭: OR 스코프가 전국으로 풀리는 실해 방지)로 결정 해소(사용자 승인). 리포트 `reports/extract/`.

## 검색 백엔드 (`0ca9ddd`)

- `POST /api/search` → 추출 → `trip_ids_for_places`(photos 테이블 자기일관 — ISO 매핑 불요) → `semantic_search_photos(원문, keywords_en, trip_ids, …)` → KST lane(관련도순 = 그룹 내 최고 rank, D26-⑦). 빈 query 422·ollama `ConnectionError` 503 한국어 detail. 라우트 코어는 `run_search`/`group_by_kst_date` 공용 함수(골든 러너가 HTTP 비경유 재사용)
- **장소 단일 OR 그룹**: `PhotoQueryFilters.trip_ids` + `(country LIKE OR city/district LIKE OR trip_id IN)` — "이탈리아"에 geocode 사진과 GPS 무 trip 사진이 함께 회수(구 Claude의 list_trips 우회 대체). 단수 trip_id는 독립 AND 유지
- PhotoSummary/PhotoDetail에 좌표 추가(ADR-0009 §3) — privacy 테스트는 "좌표 포함 + image_path·PII 부재 유지"로 의도 갱신
- 실검색: "몽골 은하수" → 2018-07-16 Булган rank 1(몽골 trip이 상위 4 lane) · "이탈리아 돌로미티" → Cortina d'Ampezzo rank 1 · 지연 웜 1~5s(콜드 ~9s)

## 채팅 일괄 삭제 (`7533de3`, prd §6-f)

engine·ollama_chat·Gradio app·routes/chat + 테스트 21건 삭제. deps(engine·chat_lock·transcript)→extractor. cli `serve` 삭제·`--backend/--model` 제거(`--ollama-host`=추출기). pyproject `anthropic`·`gradio` 제거(`uv lock`+`uv pip install`, sync 회피). `grep anthropic|gradio` 0건. 구 `/api/chat*` 404 회귀 테스트. **`ANTHROPIC_API_KEY` 요구 소멸.**

## 검색 UI (`2bd631a`)

SearchBar(하단 상시·z-index 시트 위·제출 시 blur)·ResultsSheet(해석 칩 + fallback "⚠️ 단순 의미 검색" 배지)·ResultLanes(DateLanes 개조 — 접힘 5장+'더보기', 뷰포트 ~3장 marquee)·지도 주황 하이라이트(별도 source ≤50, 최상위 lane fitBounds, 해제 시 제거)·**returnTo='search'**(더보기→날짜 상세→닫기→검색 복귀; 클러스터 진입은 검색 컨텍스트 소멸 — store 주석에 상태 머신 명문화).

## 2026-06-21 follow-up — intent router + trip summary

`QueryExtractor` 출력에 `answer_type`(`fact`/`photo_list`)을 추가하고, `is_date_intent()` fallback으로 짧은 날짜/여행 시점 질의가 `photo_list`로 떨어지는 경우를 보정. `POST /api/search`는 fact형 국가 질의에 대해 로컬 `trips` 기반 `trip_summary`를 반환하고, ResultsSheet는 summary 카드를 사진 lane 위에 보조 노출한다. 사진형 질의는 기존 lane 중심 UX 유지.

검증(master, 2026-06-21): `pytest -q` 359 passed, `ruff check .` PASS, `npm run build` PASS(Vite chunk warning만), real data golden PASS=10 FAIL=0, API smoke `이탈리아 언제 갔어` → `answer_type=fact`·`trip_summary=1`, `은하수 사진` → `photo_list`·`trip_summary=0`.

## golden v2 러너 (`04d515e`)

`eddr golden` — 검색 파이프라인 직접 호출·**match 3종 기계 판정**(`photo_ids_any`·`date_lane_top{date,within}`·`caption_contains_any{words,top_k}`, 복수 AND, 알 수 없는 키·형식 오류는 FAIL). match 미작성 = 보류(분모 제외) + 추출·상위 lane·캡션 미리보기 리포트(`reports/golden/20260612_1531_v2_*`) — **match 작성은 사용자 몫**(규약: 러너는 정답을 만들지 않음, yaml 비수정).

## 리뷰 2단계 → 수정 (`d6a2212`)

스펙 리뷰 **7/7 ✅ 위반 0**. 품질 리뷰 4건:
- **C1(Critical) KST 날짜 경계 시프트**: naive 경계가 SQLite `datetime()`에서 UTC로 오해석 → 필터 윈도 +9h(KST 새벽 누락·익일 오염, KST 그룹핑과 자기모순). **`_kst_bound`**(tools.py)가 bare 날짜를 `T00:00:00+09:00`/`T23:59:59+09:00`로, naive datetime에 +09:00 부여 — photos(aware)·trips(naive UTC) 양 경로가 `datetime()` UTC 변환으로 정합. 경계 회귀 테스트 추가. **교훈: aware 컬럼과 naive 바인딩의 혼합은 조용한 9h 시프트 — 경계 생산 지점에서 aware 강제**
- I1: golden `evaluate_match`를 문항 try 안으로 + match 값 형식 검증(str-as-list 글자 순회 거짓 판정 차단)
- I2: SearchBar 제출 시 input blur(iOS 키보드가 결과 시트 가림)
- I3: summary 엔드포인트 주석 현행화(소비처 삭제됨 — prd "유지" 결정대로 보존)

## 수치

pytest **240 passed** · 번들 gzip ~353KB · Playwright 모바일 전 흐름 PASS(콘솔 에러 0). **잔여 게이트**: 사용자 match 규칙 작성 → `eddr golden` 9문항 중 8↑(G06은 M4로).

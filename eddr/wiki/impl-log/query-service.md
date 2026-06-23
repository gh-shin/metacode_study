---
title: "⑦ 질의 레이어 — 5 tools + Claude 챗 엔진 + Gradio serve"
source: ["docs/adr/0003-llm-tool-surface.md", "docs/adr/0001-privacy-boundary.md", "docs/PLAN.md#6"]
last_verified: 2026-06-11
status: fresh
confidence: high
tags: [query, tools, claude-api, gradio, serve]
---

# ⑦ 질의 레이어 구현 (2026-06-11)

`eddr serve`로 전체 서비스(Gradio 채팅 → Claude tool use → 5 tools → 답변+사진 그리드)가
동작한다. 커밋 `22b09f4`(데이터 레이어) · `15ec542`(엔진+UI). 테스트 suite 144→**165 passed**.

## 모듈 구조

```
src/eddr/query/
  captions.py    # P3_hybrid 캡션 파서 — Search keywords 머리말 bold/plain 모두 처리
  tools.py       # QueryService — 5 tools 구현 + 응답 dataclass(privacy 스키마)
  engine.py      # ChatEngine — anthropic SDK manual tool use loop + 한국어 시스템 프롬프트
  ollama_chat.py # OllamaChatClient — anthropic 호환 어댑터(로컬 모델 백엔드, ⑧ 선행 검증용)
  app.py         # Gradio Blocks UI + serve() — 채팅·사진 그리드·인덱싱 footer
```

## 핵심 결정·구현 노트

- **privacy는 스키마로 강제(ADR-0001)**: `PhotoSummary`/`PhotoDetail`/`TripSummary`/`TripDetail`에
  latitude·longitude·image_path·source_uri **필드 자체가 없다**. 테스트가
  `dataclasses.fields()`로 부재를 고정. 이미지 경로는 `QueryService.image_path()`
  side-channel — UI 렌더 전용, LLM 미전송.
- **dedup 필터(PLAN §4.2)**: `repository._photo_filter_sql()`이 모든 질의 경로에
  `duplicate_of IS NULL`·`indexing_status != 'skipped_video'`를 무조건 주입 — tool이
  어떤 필터 조합을 짜도 누락 불가. `get_photo`는 duplicate id 조회 시 canonical을 반환.
- **GPS 무 사진 분리(사용자 제안 2026-06-10)**: 정렬 첫 키 `(p.country IS NULL)`로
  geocode 있는 사진 우선 + `has_location` 필드. 시스템 프롬프트가 "false면 장소 답변
  근거로 쓰지 말고 구분해 언급"을 지시.
- **rank 기반 거리(노트북 05 §D-4)**: semantic 응답은 rank(1부터)가 1차 신호, distance는
  참고용. tool description과 시스템 프롬프트 양쪽에 "절대값 컷오프 금지" 명시.
- **semantic over-fetch**: Chroma 메타데이터에는 geocode·날짜가 없음(photo_id·source·
  kind·model_id뿐) → k×5 over-fetch 후 `filter_photo_ids()`로 SQL 후처리(dedup 포함,
  거리순 보존) → 상위 k. 지명·날짜 필터 합성 실측: "바다"+대한민국+2014↑ → 인천·서귀포 해변.
- **list_trips 국가 매칭**: trip_countries는 ISO 코드라 한국어 질의와 직접 매칭 불가 →
  trip 이름 LIKE **또는** 소속 사진 photos.country LIKE (사용자 결정 반영). 날짜 범위는
  trip 기간과의 **겹침** 판정.
- **caption 파서**: `Search keywords:` 머리말이 bold(4,370)·plain(5,013) 혼재 — 정규식
  `\*{0,2}Search keywords:\*{0,2}` 하나로 분리, 응답은 body·keywords 구조화.
- **ChatEngine**: manual loop(최대 8왕복 안전장치), adaptive thinking, system 프롬프트
  `cache_control: ephemeral`(인덱싱 상태 N/M·오늘 날짜는 엔진 생성 시 고정 — 세션 내
  캐시 유지). tool 오류는 `is_error` tool_result로 돌려 LLM이 재시도. 기본 모델
  `claude-opus-4-8`, `eddr serve --model`로 오버라이드.
- **ollama 로컬 백엔드(사용자 결정 2026-06-11, 비용절감)**: `eddr serve --backend ollama
  [--model qwen3.6:27b] [--ollama-host URL]`. `OllamaChatClient`가 ChatEngine의 `client=`
  주입점에서 anthropic↔ollama를 양방향 번역(합성 tool id·is_error는 `ERROR:` 접두 인코딩·
  `num_ctx` 32k 명시 — 기본 4k는 tool 정의+이력이 잘림). thinking·cache_control은 무시,
  `think` 파라미터는 명시 시에만 전송(미지원 모델 보호). 로컬 모델이라 ADR-0001 외부 전송
  자체가 없음. v1 최종 답변 모델은 여전히 Claude(실 API 채점은 ⑧).
- **Gradio UI(gr 6.17)**: Chatbot(messages 기본형 — `type=` 인자는 6에서 제거됨)·
  Gallery(5열)·인덱싱 footer. HEIC 등 브라우저 미지원 포맷은 pillow-heif로 JPEG 썸네일
  변환(`data/cache/thumbs`, 경로 sha1 캐시) — photos_library 8,574장이 HEIC 다수라 핵심 경로.
  ANTHROPIC_API_KEY 부재는 챗 버블로 안내.

## 실DB 검증 (2026-06-11)

- indexing_stats **9,218/9,218**(영상·dup 제외 모집단 100%) — footer 표기.
- R1 즉답 재현: `list_trips(몽골)` → trip_20180713_01(448장, CN·MN) ·
  `list_trips(이탈리아)` → trip_20190629_01(278장, IT).
- semantic "오로라" → 아이슬란드 오로라 top-1·2 적중(GPS 무 사진도 매칭, has_location=false).
- `eddr serve` 기동 HTTP 200(4s) + Playwright E2E(입력→챗 표시→키 부재 안내) PASS.
- **API 키 실호출은 미검증**(환경에 ANTHROPIC_API_KEY 없음) — 엔진 로직은 fake client
  mock 5건으로 고정. 실 E2E는 키 설정 후 ⑧ 골든셋에서.
- **ollama 실 스모크(2026-06-11, qwen3.6:27b·48GB RAM)**: tool use 루프가 실 LLM에서
  완전 동작 — R1 "몽골 언제?" → `list_trips(몽골)` → 2018-07-13~21·중국 포함·448장
  즉답(75.9s, 콜드로드 포함). R3 "오로라 사진" → `semantic_search_photos(오로라)` →
  20장(아이슬란드, GPS 무 사진 구분 언급 — 시스템 프롬프트 준수)(328.5s — thinking이
  길어 felt-slow, 무비용 회귀용으로는 수용). mock-only였던 엔진 경로의 실 모델 검증 완료.

## 발견·후속

- **image_path 상대경로 실측 정정**: local 1,730만 절대경로, **photos_library 8,574·
  takeout 1,385는 상대경로**(기존 TODO 메모 "takeout만 상대"는 부정확). `eddr serve`는
  repo 루트에서 실행해야 사진이 보인다 — 통일 작업은 TODO 코드품질 항목.
- get_trip(몽골) top_cities에 몽골 현지어 지명(Сэврэй 등) — Nominatim ko가 소도시는
  현지어 반환. 답변 품질 이슈 시 후속.

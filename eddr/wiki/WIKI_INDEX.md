# WIKI_INDEX

> wiki/ 전체 목차. 작업 시작 시 먼저 읽고 관련 page만 로드한다. 프로토콜: `AGENTS.md`.
> 200행 초과 시 디렉터리별 하위 INDEX로 분리.

## decisions/ — 결정의 컴파일된 요약
- [privacy.md](decisions/privacy.md) — Privacy 경계: PII·이미지·정밀좌표 외부 LLM 전송 금지 (ADR-0001)
- [photo-identity.md](decisions/photo-identity.md) — Photos asset 1=1행, dedup=cross-source만 (ADR-0002)
- [tool-surface.md](decisions/tool-surface.md) — (archived) LLM tool 5개 — ADR-0009로 superseded, QueryService는 내부 검색 서비스로 존속
- [local-search.md](decisions/local-search.md) — **D26 지도 중심 로컬 검색 전환**: 채팅 폐기·런타임 LLM 로컬화·좌표 로컬 노출·KST 날짜 (ADR-0009)
- [eda-scope.md](decisions/eda-scope.md) — D8 near-dup 보류·D10 person 질의 폐기 (ADR-0004)
- [google-takeout-source.md](decisions/google-takeout-source.md) — Google Takeout 3번째 소스, [2011,C) 날짜 gap-fill, dedup 우회 (ADR-0005)
- [vector-store.md](decisions/vector-store.md) — Chroma sidecar 채택, FAISS/sqlite-vec 제외 (ADR-0006)
- [lan-distributed-vision.md](decisions/lan-distributed-vision.md) — 로컬 caption을 사용자 사설 LAN 노드로 분산, embed는 로컬 단일 (ADR-0007)
- [web-server-contracts.md](decisions/web-server-contracts.md) — 웹 API 서버 3계약: server 위치·photo_id 간접 서빙/EDDR_ROOT·무인증 가드 (ADR-0008)
- [decision-log.md](decisions/decision-log.md) — D1–D25 전체 결정 압축

## architecture/ — 스키마·파이프라인·흐름
- [db-schema.md](architecture/db-schema.md) — SQLite 테이블 인벤토리 (PLAN §4)
- [indexing-pipeline.md](architecture/indexing-pipeline.md) — 인덱싱 파이프라인 (PLAN §5)
- [query-flow.md](architecture/query-flow.md) — D26 로컬 검색 파이프라인: gemma4:e2b 추출→RRF 융합→날짜 lane (PLAN §6 v2)
- [web-app.md](architecture/web-app.md) — D26 전환 중 웹 앱: FastAPI+React 지도 검색 SPA — 목표 레이아웃·API 표면·삭제 예정 표면

## models/ — 모델 선택 추적
- [model-decisions.md](models/model-decisions.md) — SOLUTION_REVIEW 권고 status (전부 pending, A/B는 Vision 단계)

## data-profile/ — 실측 데이터
- [eda-findings.md](data-profile/eda-findings.md) — 3소스(icloud·local·google_takeout) EDA 핵심 수치 + vision_manifest 3,122

## research/ — 외부 근거
- [context-engineering.md](research/context-engineering.md) — context pollution 연구·LLM Wiki 패턴 비교

## impl-log/ — 구현 기록
- [_index.md](impl-log/_index.md) — 구현 로그 인덱스
- [google-takeout-staging.md](impl-log/google-takeout-staging.md) — Takeout 적재 파이프라인(ADR-0005)·C=2017·실데이터 1,385장 적재(Task 7 완료)·RAW/영상 skip 측정·보류
- [foundation-db-chroma.md](impl-log/foundation-db-chroma.md) — Foundation DB + Chroma 구축·CLI 사용법·적재 현황(captions 9,383 정합)·검증 노트북 05 강화(12게이트 ALL PASS·실사용 질의 §D-5)·load-sources 안전 수정 완료(`b5e230d`)
- [dedup-geocode-radius.md](impl-log/dedup-geocode-radius.md) — ④ 구현(2026-06-10): 신규 4테이블+photos 5컬럼, 해시 백필 7,653·dedup 마킹 165(canonical 전부 photos_library), Nominatim geocode(3dp 캐시·ko), Daily Radius 격자 후보+wizard
- [trip-clustering.md](impl-log/trip-clustering.md) — ⑥ 구현(2026-06-11): ISO country_code 백필 2,047셀·9개국, 세그멘테이션(복귀 주신호+갭 72h·24h+ 스팬), 실DB 83 trips·배정 3,760(no-GPS 758), 거주국 제외 trip_countries, R1 즉답(몽골 2018-07·이탈리아 2019-06)
- [query-service.md](impl-log/query-service.md) — ⑦ 구현(2026-06-11): 5 tools(privacy 스키마 강제·dedup·GPS 분리·rank 거리)·Claude 챗 엔진(adaptive thinking·캐싱)·Gradio serve(HEIC 썸네일), 실DB R1 즉답·semantic 오로라 top-1·E2E PASS — 서비스 동작. +ollama 로컬 백엔드(`--backend ollama`, qwen3.6:27b 실 스모크 PASS — 무비용 ⑧ 선행 검증)
- [golden-regression.md](impl-log/golden-regression.md) — ⑧ 진행(2026-06-11): 골든셋 v1 사용자 선별(R2 0문항·confirmed 대기)·`eddr golden` 러너(JSONL 증분+채점 md)·1차 ollama 2 runs(think on 36분/off 13분, 잠정 강통과 7) — think A/B 결론: ollama 레그 `--no-think` 권장·본선 Claude는 adaptive 유지. G04 수정 검증(`list_trips` 설명), 잔여: 사용자 채점 → 2차 실 API
- [retrieval-quality.md](impl-log/retrieval-quality.md) — 검색품질(2026-06-11): RRF·reranker 실측 **기각**, 채택은 adaptive over-fetch·질의 instruction·필터 의미론 가이드(geocode 천장 → trip_id 유도) — 벤치 norm 0.378→0.739, E2E G02/G03/G09 대폭 개선. 마이크로벤치 `scripts/bench_retrieval.py`·리포트 `reports/retrieval/`
- [caption-quality-audit.md](impl-log/caption-quality-audit.md) — 캡션품질(2026-06-13): 냉면↔콩나물/숙주 오염을 caption false positive와 retrieval amplification으로 분리, `eddr search audit`·food guard prompt·selected photo prompt-ab 추가, qwen3-vl 후보 우세
- [web-server-m1.md](impl-log/web-server-m1.md) — D25 M1: FastAPI 서버(chat·photos/thumb·status)·EDDR_ROOT 계약, /tmp 기동+curl G08 수용 PASS
- [notes-m5.md](impl-log/notes-m5.md) — D26 M5(2026-06-12): 사진 메모 — notes·note_text 임베딩(별도 컬렉션)·RRF note leg(거리 경쟁 정규화, 편차 승인)·NoteEditor, 실DB 가역 E2E(rank 1 합류·흔적 0)
- [geocode-m4.md](impl-log/geocode-m4.md) — D26 M4(2026-06-12): 수동 지오코딩 — no-location 525그룹·Nominatim search 프록시·일괄 지정(reverse 주소 통일)·long-press, 리뷰 C1(재적재 manual 좌표 보존) 수정 — 게이트는 사용자 개심사 실지정
- [local-search-m3.md](impl-log/local-search-m3.md) — D26 M3(2026-06-12): 로컬 검색 전환(추출 게이트·OR 스코프·KST lane)+채팅 일괄 삭제(외부 LLM 0회)+golden v2 러너, 리뷰 C1(KST 날짜 경계 시프트) 수정 — 게이트는 사용자 match 작성 대기
- [map-shell-m2.md](impl-log/map-shell-m2.md) — D26 M2(2026-06-12): MapLibre 지도 셸 — GeoJSON 5,587점·클러스터 탭 즉시 표출·시트 드래그 dismiss·썸네일 prefetch·Tailscale HTTPS(폰 검증 PASS), 리뷰 2단계 통과
- [kst-normalization.md](impl-log/kst-normalization.md) — D26 M1(2026-06-12): taken_at 전량 KST aware 백필 — 진단(photos_library 실측 전량 UTC·local 벽시계), 달력일 변경 1,743, Photos 대조 5/5, trips 83→82, sqlite3 backup 자기교착 트러블슈팅
- [web-spa-m2.md](impl-log/web-spa-m2.md) — D25 M2: web/ React SPA(채팅·그리드·라이트박스, gzip 63KB)+history·original·SPA 서빙, 모바일 E2E PASS — **D26으로 superseded**(채팅 표면은 M3 삭제, 라이트박스·썸네일·서버 인프라는 계승)

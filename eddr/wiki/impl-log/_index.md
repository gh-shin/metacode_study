---
title: "구현 로그 (인덱스)"
source: []
last_verified: 2026-06-11
status: fresh
confidence: high
tags: [impl-log]
---

# 구현 로그

구현 착수 후 이슈·해결·학습을 page별로 기록한다.
INGEST 시점: 모듈 구현 완료마다 `wiki/impl-log/<topic>.md` 추가 + 본 인덱스·`WIKI_INDEX.md` 갱신.

- [google-takeout-staging.md](google-takeout-staging.md) — Google Takeout 적재 파이프라인(ADR-0005): 맥 히스토그램·C=2017·5모듈·19테스트. Task 7 실데이터 대기.
- [foundation-db-chroma.md](foundation-db-chroma.md) — Foundation DB + Chroma 구축: SQLite ledger, Photos export wrapper, Vision batch, semantic search CLI, 현재 적재/미완료 상태.
- [dedup-geocode-radius.md](dedup-geocode-radius.md) — ④ 구현: 스키마 4테이블+5컬럼 마이그레이션, 해시 백필 7,653, cross-source dedup 165건, Nominatim geocode 캐시, Daily Radius wizard(사용자 실행 대기).
- [trip-clustering.md](trip-clustering.md) — ⑥ 구현: ISO country_code 백필, 복귀 주신호 세그멘테이션, 실DB 83 trips·배정 3,760, trip_countries 거주국 제외.
- [query-service.md](query-service.md) — ⑦ 구현: 5 tools(privacy 스키마 강제)·Claude 챗 엔진(tool use loop)·Gradio serve, 실DB R1 즉답 재현·E2E PASS.
- [golden-regression.md](golden-regression.md) — ⑧ 진행: 골든셋 v1·`eddr golden` 러너·1차 ollama 채점 9/10(대행), 2차 실 API 대기.
- [retrieval-quality.md](retrieval-quality.md) — 검색품질: RRF·reranker 실측 기각, adaptive over-fetch·질의 instruction 채택(norm 0.378→0.739).
- [web-server-m1.md](web-server-m1.md) — D25 M1: FastAPI 서버(chat·photos/thumb·status)·EDDR_ROOT 계약·임의 디렉터리 기동+curl G08 수용.
- [web-spa-m2.md](web-spa-m2.md) — D25 M2: web/ React SPA(채팅·그리드·라이트박스)+history·original·SPA 서빙, 모바일 E2E PASS — 폰 골든셋 게이트 대기.

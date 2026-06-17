# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

**EDDR (어디더라?)** — 내 사진(~1만 장, 실측 약 9천)의 메타데이터·이미지 분석 결과를 로컬 SQLite·Chroma로 인덱싱하고, 한국어 자연어 질문에 **로컬 하이브리드 검색(질의 시 외부 LLM 0회, D26·ADR-0009)**으로 "언제·어디서·누구랑·뭘 했는지"를 찾아 보여주는 **개인용·로컬·단일 사용자** 사진 검색 앱. macOS 전용 (Photos Library + 로컬 vision).

**현재 상태**: **D26 지도 중심 로컬 검색 전환(ADR-0009) — 질의 시 외부 LLM 0회 달성**. Claude tool-use·Gradio 채팅은 폐기(M3에서 일괄 삭제), 검색 코어(QueryService)는 계승. 마일스톤(SoT: `docs/prd.md` v2·M0~M6): M0 문서개정·M1 taken_at KST 정규화·M2 지도 셸+Tailscale HTTPS(폰 검증 PASS) **완료**; M3 로컬검색+채팅삭제·M4 위치미상 워크플로·M5 사진 메모 **구현·리뷰 완료(게이트만 잔여 — (사용자) golden match 규칙 작성·폰 수동 지오코딩)**; M6 운영마감은 선택 백로그. `eddr serve-api`(FastAPI, `EDDR_ROOT` 계약)가 API + `web/dist` SPA(지도·그리드·라이트박스, 모바일 퍼스트)를 서빙. SQLite(`data/eddr.sqlite`) photos 11,689·captions 9,383(그 중 **1,393장 큰 모델 재캡션** — gemma4:31b 995/qwen3-vl:8b 398, 재임베딩 100% 정합)·embeddings 9,383·duplicate_of 165·geocode 7,888(한국어 지명, city 100%)·trips 83(배정 3,760), Chroma 9,383벡터, 질의 노출 모집단 9,218(영상·dup 제외). RAG 품질: query embedding instruction 채택(retrieval recall 0.644→0.732), E2E 골든 9/10. 채점은 **v2 자동**(`eddr golden`→`POST /api/search`, 외부 LLM 0회). ⑧ 실 Claude API 채점은 ADR-0009로 **공식 폐기**(채점 대상 ChatEngine 소멸). 검증 패턴은 `notebooks/05_index_verification.ipynb`. 설계·ADR·코드 모두 git 커밋됨.

## 문서 체계 (세션 시작 시)

3-layer 문서 체계를 쓴다. 상세 프로토콜은 **`AGENTS.md`**.
- **Schema** (항상 로드): `CLAUDE.md`, `CONTEXT.md`, `AGENTS.md`, `wiki/WIKI_INDEX.md`
- **Wiki** (컴파일된 지식, on-demand): `wiki/` — 먼저 `wiki/WIKI_INDEX.md` 읽고 관련 page만 로드
- **Source** (권위 원본, 읽기전용): `docs/PLAN.md`, `docs/adr/`, `docs/SOLUTION_REVIEW.md`, `docs/scenario.md`·`docs/prd.md`(웹 앱, D26)

→ **작업 시작**: `wiki/WIKI_INDEX.md` + `AGENTS.md` 읽기. **진행 상태**: `TODO.md`.

## 불변 규칙 (위반 = 틀린 구현)

- Privacy 경계 → `wiki/decisions/privacy.md` (ADR-0001)
- Photo 정체성 → `wiki/decisions/photo-identity.md` (ADR-0002)
- LLM Tool Surface 5개 → `wiki/decisions/tool-surface.md` (ADR-0003)
- EDA 스코프(D8 보류·D10 폐기) → `wiki/decisions/eda-scope.md` (ADR-0004)
- 전체 결정 로그 → `wiki/decisions/decision-log.md`

## 기술 스택 / 빌드 순서

- 스택·CLI·빌드순서 → `docs/PLAN.md` §7·§10. 모델 선택 status → `wiki/models/model-decisions.md`
- 아키텍처 요약 → `wiki/architecture/`. 실측 데이터 → `wiki/data-profile/eda-findings.md`

## 완료 기준

- Done = 골든셋 10문항 중 8개↑ 통과. 분포는 ADR-0004로 R2 재정의 필요(→ `TODO.md`). 골든셋은 **사용자가 직접 작성**(Claude가 대신 작성하지 않음).

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

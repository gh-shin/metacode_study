---
title: "Context Engineering & LLM Wiki 패턴"
source: ["docs/SECOND_BRAIN_DESIGN.md#5", "docs/SECOND_BRAIN_DESIGN.md#7"]
last_verified: 2026-06-01
status: fresh
confidence: medium
tags: [research, context-engineering, llm-wiki]
---

# Context Engineering & LLM Wiki 패턴

## (a) 학술 근거 (SECOND_BRAIN_DESIGN §5)

| 연구 | 핵심 기여 | EDDR 적용 포인트 |
|------|-----------|----------------|
| **CodeDelegator** (arXiv:2601.14914) | Ephemeral-Persistent State Separation: planner와 coder의 context 분리로 context pollution 해결 | wiki를 persistent knowledge로 유지, 작업별 context는 ephemeral |
| **Anthropic Context Engineering** (2025.09) | Selection · Compression · Ordering · Isolation · Format Optimization 5원칙 | WIKI_INDEX → selective loading, 중요 정보를 Schema Layer에 배치 |
| **HiRAG** (arXiv:2503.10150) | 계층적 검색으로 multi-level abstraction 구축 | 3-layer 계층 구조, index-first navigation |
| **Context Rot / Context Morph** (Morph, 2026) | frontier 모델 18개 전부에서 context 길이↑ → 성능↓. 100K token에서 50%+ accuracy drop | context budget 14KB 목표의 근거 |
| **Memory for Autonomous LLM Agents** (arXiv:2603.07670) | write-manage-read loop 형식화, 5가지 memory mechanism | INGEST-QUERY-LINT 3-operation 설계 |
| **Complexity Trap** (arXiv:2508.21433) | 단순한 observation masking이 LLM summarization만큼 효과적 | over-engineering 경고 → lifecycle 4단계로 단순화 |

## (b) 구현체 비교 (SECOND_BRAIN_DESIGN §7)

| 구현체 | 접근 | 장점 | 단점 | EDDR 적합성 |
|--------|------|------|------|-------------|
| **Karpathy LLM Wiki** (원본 패턴) | markdown 파일 + index.md | 인프라 0, 단순 | lifecycle 관리 없음 | ★★★★ 기반 채택 |
| **Pratiyush/llm-wiki** | MCP server + session 자동 수집 | 12개 tool, 세션 히스토리 보존 | TypeScript 의존, 과도한 기능 | ★★ 참조만 |
| **rohitg00/agentmemory** | 4-tier memory + hybrid search | 51개 tool, 다중 에이전트 | SQLite+vector, 복잡한 설정 | ★ 과도 |
| **LLM Wiki v2** (rohitg00 gist) | lifecycle + confidence scoring | stale 방지, typed relationship | 1인 프로젝트에 과도 | ★★★ lifecycle만 채택 |
| **OmegaWiki** | 연구 논문 lifecycle 전체 | 26개 skill, bilingual | 연구용, 소프트웨어 개발과 무관 | ★ 부적합 |

## (c) EDDR 선택

**Karpathy 원본 패턴 + LLM Wiki v2의 lifecycle 4단계.**

- 인프라 없이 markdown 파일만으로 운용 (embedding/vector store 불필요)
- Lifecycle: `fresh → verified → stale → archived` (30일/60일 전환 기준)
- 세션 시작 context 목표: ~14KB (~4,500 tokens) — 현재(~20K tokens) 대비 70% 절감
- YAGNI: confidence scoring, embedding index 등은 v2 후보

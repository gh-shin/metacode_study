# AGENTS.md

> EDDR의 문서 워크플로우 규약. 에이전트는 작업 시작 시 이 파일과 `wiki/WIKI_INDEX.md`를 읽는다.
> 설계 근거: `docs/SECOND_BRAIN_DESIGN.md`.

## 1. 3-Layer 문서 모델

| Layer | 파일 | 소유 | 로드 |
|---|---|---|---|
| **Schema** | `CLAUDE.md`, `CONTEXT.md`, `AGENTS.md`, `wiki/WIKI_INDEX.md` | 인간/공용 | 항상 |
| **Wiki** | `wiki/` 아래 topic별 markdown | LLM(에이전트) | index 보고 on-demand |
| **Source** | `docs/PLAN.md`, `docs/adr/`, `docs/SOLUTION_REVIEW.md`, `docs/01_eda_findings.md`, `docs/scenario.md`, `docs/prd.md` | 인간 | 읽기전용, 필요 시 drill-down |

## 2. 권위 규칙 (중요)

- **Source > Wiki**: 충돌 시 Source가 맞고 wiki를 수정한다.
- **Source가 outdated면 Source부터 고친 뒤 wiki를 갱신**한다. wiki가 source를 우회해 사실상 SoT가 되는 것을 금지.

## 3. Wiki Page Frontmatter 규격

```yaml
title: "..."
source: ["docs/adr/0001-privacy-boundary.md", "docs/PLAN.md#D6"]
last_verified: 2026-06-01
status: fresh        # fresh | verified | stale | archived
confidence: high     # high | medium | low
tags: [privacy, pii]
```

## 4. Lifecycle

`fresh ──30일──> verified ──60일/소스변경──> stale ──> archived`
- **fresh**: 최근 생성/갱신, source 일치 확인됨
- **verified**: 30일 경과, 유효하나 재검증 권장
- **stale**: 60일 경과 또는 source 변경 감지 → LINT가 flag
- **archived**: 무효 page, context 로드 제외
- 복잡한 scoring·decay는 미채택(1인 프로젝트).

## 5. 3 Operation

### QUERY (작업 시작 시)
1. `wiki/WIKI_INDEX.md` 읽기 → 관련 page 식별
2. 관련 wiki page만 selective 로드
3. 필요 시 `source` frontmatter 따라 원본 drill-down
4. 작업 수행

### INGEST (의사결정/구현 완료 시에만 — 일상 코드 수정엔 불필요)
1. 관련 wiki page 갱신/신규
2. 연쇄 page(architecture/·models/ 등) 갱신
3. `wiki/WIKI_INDEX.md` 목차 갱신
4. frontmatter `status: fresh`, `last_verified: <today>`

### LINT (주기적/요청 시 — 코드 자동화 아님, 에이전트 절차)
1. 전 page frontmatter 스캔 → stale 목록
2. 각 page `source` 경로 존재·일치 검증
3. source↔wiki 불일치 탐지 → 리포트
4. WIKI_INDEX 누락/orphan 링크 점검
5. (사용자 확인 후) wiki 갱신 또는 source 수정 제안

## 6. INDEX 분리 규칙

`wiki/WIKI_INDEX.md`가 200행 초과 시 디렉터리별 하위 INDEX로 분리한다.

## 7. TODO 아카이빙 (ARCHIVE) — 각 작업 시 필수

`TODO.md`는 **미완료 항목만** 유지한다. 항목이 완료되면 체크(`[x]`)만 하고 두지 말고 **즉시**:

1. `TODO.md`에서 제거하고 [`TODO_ARCHIVE.md`](TODO_ARCHIVE.md)로 이관한다.
2. 이관 항목에 **완료 날짜·시각(분단위)** 과 **대표 git commit hash**를 함께 기재한다.
   - 형식: `- [x] <항목> — 완료 YYYY-MM-DD HH:MM · commit <hash>`
   - 출처: 시각은 `date "+%Y-%m-%d %H:%M"`, hash는 `git log`(작업을 대표하는 커밋).
3. `TODO_ARCHIVE.md`는 날짜 헤더별 **최신순**으로 정리한다.
4. `TODO.md` 상단 '최종 갱신'을 날짜·시각으로 갱신한다.

목적: TODO를 실제 할 일 목록으로 가볍게 유지하고, 완료 이력을 시각·커밋과 함께 추적 가능하게 보존한다.

# Subagent 사용 규칙
- 품질, 판단 등 사고력이 필요한 경우는 subagent라 할지라도 opus 이상 모델을 유지한다.
- 항목과 기능이 명확히 정해진 업무에만 sonnet 사용을 검토한다.
- 단순 파일 리스트업, 텍스트 summary 등의 업무에만 haiku를 사용한다.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, invoke the `skill` tool with `skill: "graphify"` before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Imported Claude Cowork project instructions

CLAUDE.md파일을 참조하세요.
기술 선택은 항상 arxiv 등 기존의 연구를 토대로 이뤄져야합니다.

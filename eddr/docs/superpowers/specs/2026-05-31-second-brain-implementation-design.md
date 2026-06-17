# EDDR Second-Brain 구현 설계 (Implementation Spec)

> **대상**: `docs/SECOND_BRAIN_DESIGN.md` 기획안의 **전체 구현**
> **작성일**: 2026-05-31 | **상태**: 승인됨 (구현 대기)
> **선행**: brainstorming 세션 — 사용자 "전체 설계 동의" 확정

---

## 1. 목적과 범위

`SECOND_BRAIN_DESIGN.md` §3.1이 규정한 3-layer 문서 아키텍처(Schema / Wiki / Source)를 **문자 그대로 전체 실현**한다. 목표는 프로젝트 성장 시 context pollution 방지 + 에이전트가 의사결정·구현 시 self-contained wiki를 QUERY/INGEST/LINT 워크플로우로 활용·갱신하는 체계를 구축하는 것.

**범위 (In scope)**
- `wiki/` 6개 하위디렉터리 + 12개 콘텐츠 페이지 + `WIKI_INDEX.md` 신규 생성
- `AGENTS.md` 신규 — 3-layer 모델 + QUERY/INGEST/LINT 프로토콜 + frontmatter 규격 + 권위 규칙
- 전 소스 INGEST(PLAN·ADR·SOLUTION_REVIEW·EDA·SECOND_BRAIN_DESIGN → wiki 페이지)
- `CLAUDE.md` 포인터형 리팩터링 (4중 중복 제거)
- `PLAN.md` ADR-0004 반영 주석 + 규모 실측 정정
- lifecycle frontmatter 적용 + 초기 LINT self-check

**비범위 (Non-goals)**
- LINT의 **코드 자동화** — AGENTS.md의 에이전트 절차로만 정의 (코드 0행 상태)
- confidence **scoring 알고리즘**·Ebbinghaus decay — status 4단계로 단순화 (§3.4)
- Phase 단계적 도입 — 사용자 결정에 따라 전체 일괄 구축
- `SOLUTION_REVIEW.md` 권고의 **수락/거부 확정** — pending 기록만 (A/B는 Vision 단계 ⑤)

---

## 2. 검증된 현재 상태 (구현 근거)

탐색으로 확인한 실측 상태. 기획안의 스냅샷(`9개/63.6KB`)은 이미 stale했으며 아래가 정확하다.

- **파일**: 루트+docs 마크다운 **11개 / ~88KB**. 항상 자동 로드는 CLAUDE.md+CONTEXT.md ≈ **13KB**.
- **PLAN.md outdated (실재 버그)**: D8(near-dup)·D10(person 질의)을 여전히 active로 기술. 스키마에 `near_duplicate_group_id`·`persons`/`photo_persons` 살아있고 골든셋 R2(5/3/2) 분포도 그대로 → ADR-0004(D8 보류·D10 폐기)와 정면 충돌.
- **SOLUTION_REVIEW.md untracked**: 모델 교체 권고가 어디에도 수락/거부 기록 없음. PLAN.md §7 스택은 옛 모델(Qwen2.5-VL 7B·BGE-M3) 그대로.
- **4중 중복 확인**: privacy·photo-identity·5-tool이 CLAUDE.md/CONTEXT.md/ADR/PLAN.md 전부에 전문 반복. CLAUDE.md는 포인터 아닌 full-text(55행).
- **빈 슬레이트**: `wiki/`·`AGENTS.md`·`WIKI_INDEX.md` 전무. 충돌 없음.
- **트리거 채점**: §9 도입표 중 `불일치 3건↑ → wiki/decisions/ 생성`만 발화(D8·D10·모델스택). `100행`·`40K 토큰`·`30 페이지` 트리거는 미충족 — 즉 전체 구축은 사용자 선택에 따른 것이며 문서의 점진 로직을 앞당기는 것임을 명시.

---

## 3. 핵심 결정 (brainstorming 합의)

| 항목 | 결정 |
|---|---|
| **구현 범위** | 전체 구축 (문자 그대로, §3.1 전부) |
| **모델 권고 status** | 기록 + 보류(pending), A/B는 Vision 단계(⑤)로 이연 |

**Default 5건 (승인됨)**

| # | 선택 | 비고 |
|---|---|---|
| 1 | PLAN.md = **주석**(삭제 안 함) | D8 보류·D10 폐기는 v2 복원 여지 보존 |
| 2 | frontmatter = §3.2 **전체 필드**(confidence 포함) | §3.4 lifecycle 4단계와 병용 |
| 3 | research/ = **1페이지 시드**, impl-log/ = stub | impl-log는 코드 착수 후 충전 |
| 4 | SOLUTION_REVIEW.md **원본 불변**, status는 wiki/models/ | Source 읽기전용 원칙 |
| 5 | decisions/ = **ADR별 4페이지 + decision-log 1** | CLAUDE.md 불변규칙 링크가 개별 페이지를 가리킴 |

---

## 4. 파일 인벤토리

```
eddr/
├── CLAUDE.md              [수정] 55행 full-text → ~35행 포인터형
├── CONTEXT.md             [유지] 변경 없음 (always-load 용어집)
├── AGENTS.md              [신규] 3-layer + QUERY/INGEST/LINT + frontmatter 규격 + 권위 규칙
├── TODO.md                [유지] 진행 추적
├── wiki/                  [신규]
│   ├── WIKI_INDEX.md      전체 목차 (페이지별 1줄 요약 + 링크, <200행)
│   ├── decisions/
│   │   ├── privacy.md            ← ADR-0001
│   │   ├── photo-identity.md     ← ADR-0002
│   │   ├── tool-surface.md       ← ADR-0003
│   │   ├── eda-scope.md          ← ADR-0004
│   │   └── decision-log.md       ← PLAN.md §3 D1–D23 컴파일
│   ├── architecture/
│   │   ├── db-schema.md          ← PLAN.md §4
│   │   ├── indexing-pipeline.md  ← PLAN.md §5
│   │   └── query-flow.md         ← PLAN.md §6
│   ├── models/
│   │   └── model-decisions.md    ← SOLUTION_REVIEW.md (status:pending 추적)
│   ├── data-profile/
│   │   └── eda-findings.md       ← docs/01_eda_findings.md
│   ├── impl-log/
│   │   └── _index.md             [stub]
│   └── research/
│       └── context-engineering.md ← SECOND_BRAIN_DESIGN §5·§7
└── docs/                  [Source Layer, 읽기전용]
    ├── PLAN.md            [수정] ADR-0004 주석 + 규모 9047 정정
    ├── SOLUTION_REVIEW.md [유지] 원본 불변
    ├── 01_eda_findings.md [유지]
    ├── SECOND_BRAIN_DESIGN.md [유지]
    └── adr/0001~0004      [유지]
```

wiki 콘텐츠 페이지 **12개** + WIKI_INDEX 1개 (LINT 트리거 30개 미만).

---

## 5. 규약 (AGENTS.md에 명문화할 내용)

### 5.1 3-Layer 모델
- **Schema** (항상 로드): CLAUDE.md, CONTEXT.md, AGENTS.md, wiki/WIKI_INDEX.md
- **Wiki** (LLM 소유·갱신): wiki/ 아래 topic별 markdown. index 보고 on-demand 로드
- **Source** (인간 소유·읽기전용): docs/PLAN.md, docs/adr/, docs/SOLUTION_REVIEW.md 등

### 5.2 Frontmatter 규격 (§3.2)
```yaml
---
title: "..."
source: ["docs/adr/0001-privacy-boundary.md", "docs/PLAN.md#D6"]
last_verified: 2026-05-31
status: fresh        # fresh | verified | stale | archived
confidence: high     # high | medium | low
tags: [privacy, llm-tool, pii]
---
```

### 5.3 Lifecycle (§3.4)
`fresh ──30일──> verified ──60일/소스변경──> stale ──> archived`. INGEST로 fresh 갱신, LINT로 stale 검증. 복잡 scoring 미채택.

### 5.4 권위 규칙
- **Source > Wiki**: 충돌 시 Source가 맞고 wiki를 수정.
- **단, Source가 outdated면 Source부터 고친 뒤 wiki 갱신** — wiki가 Source를 우회해 사실상 SoT가 되는 것을 방지. (그래서 본 작업에서 PLAN.md를 먼저 손봄)

### 5.5 3 Operation 프로토콜
- **QUERY** (작업 시작): WIKI_INDEX → 관련 page 로드 → (필요 시) source drill-down → 작업.
- **INGEST** (의사결정/구현 완료 시): 관련 wiki page 갱신 → 연쇄 페이지 갱신 → WIKI_INDEX 목차 갱신 → frontmatter status=fresh, last_verified=today.
- **LINT** (주기적/요청 시): frontmatter 스캔 → stale 목록 → source↔wiki 불일치 탐지 → 리포트 → (확인 후) wiki 갱신 또는 source 수정 제안. **코드 자동화 아님.**

---

## 6. wiki 페이지별 INGEST 명세

| 페이지 | Source | 담을 내용 |
|---|---|---|
| `decisions/privacy.md` | ADR-0001 | 이미지 바이너리·정밀좌표·PII EXIF 외부 LLM 전송 금지. 위치는 country/city/district까지. hidden 인덱싱 제외. lat/lng 로컬 거리계산 전용. |
| `decisions/photo-identity.md` | ADR-0002 | Photos asset 1 = photos 1행. 원본+보정=1(variant 미보존), Burst keeper만, Live 정지만. source_uri=UUID\|경로. dedup=cross-source만. |
| `decisions/tool-surface.md` | ADR-0003 | 정확히 5 tool(search_photos, semantic_search_photos, list_trips, get_trip, get_photo). freeform SQL 없음. list는 limit 강제. 응답 schema가 privacy 자동강제. |
| `decisions/eda-scope.md` | ADR-0004 | D8 보류(93쌍 모두 export artifact Hamming 0 → 실제율 미측정 → v1 중복 허용). D10 폐기(named 1명, INDEXABLE 12.3% → R2 recall 구조적 불가). |
| `decisions/decision-log.md` | PLAN.md §3 D1–D23 | 결정 압축 표. ADR화된 4건은 위 페이지로 cross-link. 나머지(D4 사진SoT, D19 영어캡션, D20 임베딩, D21 5tool/YAGNI 등) 1줄 요약. |
| `architecture/db-schema.md` | PLAN.md §4 | 핵심 테이블(photos, embeddings 2/사진, captions, persons/photo_persons, trips/trip_countries, daily_radius_areas, geocode_cache) + 주요 컬럼·관계. ADR-0004 v1 미사용 항목 표기. "코드 진화 시 코드 기준 갱신" 명시. |
| `architecture/indexing-pipeline.md` | PLAN.md §5 | osxphotos 추출+스캔 → hash/dedup → geocode → Daily Radius(KDE) → Vision(embed+caption) → Trip 클러스터 → upsert. recent-first, `indexing_status` 체크포인트. |
| `architecture/query-flow.md` | PLAN.md §6 | Gradio → Claude API → 5 tool → 한국어 답 → 사진 그리드. footer "N/M 인덱싱". privacy 보장 경로. |
| `models/model-decisions.md` | SOLUTION_REVIEW.md | 권고별 표 [영역\|현행\|권고\|우선순위\|status]. 전부 **status: pending**, "A/B는 Vision 단계(⑤)". P1 caption Qwen2.5-VL 7B→Qwen3-VL 8B(+Gemma4 26B 후보), P1 text-embed BGE-M3→Qwen3-Embedding-8B, P2 image-embed 통합 Qwen3-VL-Embedding(fallback SigLIP2/Jina-CLIP v2), P3 dHash 재튜닝·HDBSCAN·규모 9047. |
| `data-profile/eda-findings.md` | 01_eda_findings.md | 9,047 assets, INDEXABLE 8,574(94.8%), GPS 91%, taken_at 100%, near-dup 93쌍 Hamming 0, person 1명 12.3%, Daily Radius 존재 확인, trip 후보 44. 메타데이터 한정(Vision/iCloud EDA 별도 세션). |
| `impl-log/_index.md` | — | **stub**. "구현 착수(빌드순서 ②) 후 이슈·해결·학습 기록." |
| `research/context-engineering.md` | SECOND_BRAIN_DESIGN §5·§7 | 학술 근거 표(CodeDelegator, Anthropic Context Engineering, HiRAG, Context Rot, Memory for LLM Agents, Complexity Trap) + 구현체 비교(Karpathy/Pratiyush/rohitg00/OmegaWiki) + EDDR 선택 근거(Karpathy 원본 + lifecycle 4단계). |

`WIKI_INDEX.md`: 디렉터리별 그룹 + 페이지당 1줄 요약 + 링크. 200행 미만 유지.

---

## 7. Source Layer 수정 명세

### 7.1 CLAUDE.md (포인터형 ~35행)
- **유지**: 프로젝트 개요 1단락.
- **신규**: 문서 체계 안내(Schema/Wiki/Source) + "세션 시작 시 `wiki/WIKI_INDEX.md`·`AGENTS.md` 읽기" 지시.
- **교체**: 불변규칙 4건을 **1줄 요약 + `wiki/decisions/*.md` 링크**로 (full-text 제거).
- **포인터화**: 기술스택·빌드순서 → PLAN.md §7/§10 + TODO.md 링크. 모델 status는 `wiki/models/model-decisions.md`.
- **유지**: 완료기준(골든셋) → TODO.md 포인터.

### 7.2 PLAN.md (주석, 삭제 안 함)
- 상단(§1 부근): "⚠️ ADR-0004 반영" 배너 + 링크.
- §3 결정로그: D8 행에 "→ ADR-0004: v1 보류", D10 행에 "→ ADR-0004: 폐기" 인라인.
- §4.1 스키마: `near_duplicate_group_id`, `persons`/`photo_persons`에 "v1 미사용(ADR-0004)" 메모. (person *데이터 적재*와 *질의 폐기* 구분 유지 — 삭제 시 맥락 소실.)
- §4.2: near-dup 그룹핑 규칙에 보류 메모.
- 골든셋/§10: R2(person) 분포 재정의 필요 메모(또는 TODO.md 참조).
- 규모: `~10만 장` → `실측 9,047` 정정(등장 위치).

### 7.3 SOLUTION_REVIEW.md
- **불변**. 원본은 인간 소유 Source. status 추적은 `wiki/models/model-decisions.md`가 담당.

---

## 8. 구현 순서

```
① AGENTS.md 작성        (규약을 먼저 확정 — 이후 모든 페이지가 이를 따름)
② PLAN.md ADR-0004 주석 + 규모 9,047 정정  (outdated source부터 수정 — §5.4 권위규칙 준수)
③ wiki/ 전 페이지 INGEST (수정된 source 기준 컴파일: decisions → architecture → models → data-profile → research → impl-log stub)
④ WIKI_INDEX.md 작성     (③의 결과 목차화)
⑤ CLAUDE.md 포인터화     (wiki/decisions 링크가 ③ 이후 유효)
⑥ 초기 LINT self-check   (전 페이지가 source에 trace되는지, INDEX 누락 없는지 검증)
⑦ (사용자 요청 시) commit
```

> **순서 근거**: §5.4 "Source가 outdated면 Source부터 고친 뒤 wiki 갱신". PLAN.md(②)를 wiki INGEST(③)보다 앞에 두어, wiki가 더 정확한 상태로 source를 우회하는 구간을 만들지 않는다.

---

## 9. 완료 기준 (Done)

- [ ] `wiki/` 12개 콘텐츠 페이지 + WIKI_INDEX 생성, 각 페이지 frontmatter 완비(impl-log stub 제외)
- [ ] 모든 wiki 페이지가 frontmatter `source`로 실제 소스에 trace됨
- [ ] `AGENTS.md`에 3-layer·frontmatter·lifecycle·권위규칙·QUERY/INGEST/LINT 명문화
- [ ] `CLAUDE.md` ~35행 포인터형, 불변규칙 4중 중복 full-text 제거 → 링크화
- [ ] `PLAN.md`에 ADR-0004(D8·D10)·규모 9,047 가시화
- [ ] `WIKI_INDEX.md`에 전 페이지 등재, 200행 미만
- [ ] 초기 LINT self-check 통과(불일치 0 또는 리포트화)

---

## 10. 리스크와 완화 (§8 기반)

| 리스크 | 완화 |
|---|---|
| wiki 갱신 누락으로 stale 누적 | AGENTS.md에 INGEST 의무 명시 + LINT 절차 정의 |
| wiki가 source보다 권위를 갖는 착각 | "Source > Wiki" 규칙 AGENTS.md 명시. outdated source는 source부터 수정 |
| WIKI_INDEX 200행 초과 | 하위 INDEX 분리 규칙 사전 정의(현재는 12페이지로 여유) |
| 갱신 오버헤드 | "의사결정/구현 완료 시에만 INGEST" — 일상 코드 수정엔 불필요 |
| 전체 일괄 구축이 YAGNI 트리거를 앞서감 | 사용자 명시 결정. impl-log stub·모델 pending으로 과잉 콘텐츠 회피 |

# EDDR Second-Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docs/SECOND_BRAIN_DESIGN.md`가 규정한 3-layer 문서 아키텍처(Schema/Wiki/Source)를 전체 구축하여 context pollution을 방지하고 QUERY/INGEST/LINT 워크플로우를 확립한다.

**Architecture:** Schema Layer(항상 로드: CLAUDE/CONTEXT/AGENTS/WIKI_INDEX)가 진입점, Wiki Layer(`wiki/` 12 페이지, LLM 소유·컴파일된 지식)가 on-demand 지식, Source Layer(`docs/`, 인간 소유·읽기전용)가 권위 원본. wiki는 source에서 INGEST하고, 충돌 시 Source가 우선한다.

**Tech Stack:** Markdown only. 코드·빌드 도구 없음. 검증은 셸(`find`/`grep`/`test`) + 수동 cross-check. 승인 spec: `docs/superpowers/specs/2026-05-31-second-brain-implementation-design.md`.

---

## 작업 방식 메모 (실행 에이전트 필독)

- **이 산출물은 문서다.** 코드 테스트가 없다. 각 wiki page 작업은 (a) **완전한 frontmatter**(아래 제공) + (b) **컴파일 요구사항**(필수 사실 나열) + (c) **읽을 source**로 구성된다. 실행 시 명시된 source를 **Read**하여 요구된 사실을 명시된 구조로 컴파일한다 — second-hand 요약이 아닌 1차 source 기반 정확성을 보장하기 위함.
- **commit 정책**: 프로젝트 규칙상 git commit은 **사용자 명시 요청 시에만**. 스킬 기본값(작업마다 commit)을 따르지 않고 Task 9로 게이트한다.
- **순서 불변**: §5.4 권위규칙에 따라 outdated source(PLAN.md, Task 2)를 wiki INGEST(Task 3~5)보다 **먼저** 수정한다.
- **frontmatter 공통값**: `last_verified: 2026-05-31`, `status: fresh`.
- **기존 미커밋 변경 보존**: repo엔 이미 `TODO.md`·`docs/SECOND_BRAIN_DESIGN.md`·`docs/images/`(untracked), `CLAUDE.md`(modified)가 있다. Task 9에서 사용자 지시 없이 이들을 휩쓸지 않는다.

---

## File Structure

| 파일 | 책임 | 작업 |
|---|---|---|
| `AGENTS.md` | wiki 워크플로우 규약(3-layer·frontmatter·lifecycle·권위·QUERY/INGEST/LINT) | Task 1 신규 |
| `docs/PLAN.md` | (Source) ADR-0004·규모 불일치 주석 | Task 2 수정 |
| `wiki/decisions/{privacy,photo-identity,tool-surface,eda-scope,decision-log}.md` | 결정 컴파일 | Task 3 신규 |
| `wiki/architecture/{db-schema,indexing-pipeline,query-flow}.md` | 설계 요약 | Task 4 신규 |
| `wiki/models/model-decisions.md`, `wiki/data-profile/eda-findings.md`, `wiki/research/context-engineering.md`, `wiki/impl-log/_index.md` | 모델 status·실측·근거·stub | Task 5 신규 |
| `wiki/WIKI_INDEX.md` | 전체 목차 | Task 6 신규 |
| `CLAUDE.md` | (Schema) 포인터형 진입점 | Task 7 수정 |
| — | LINT self-check | Task 8 검증 |
| — | commit (게이트) | Task 9 |

---

### Task 1: AGENTS.md — wiki 워크플로우 규약

**Files:**
- Create: `AGENTS.md`

- [ ] **Step 1: AGENTS.md 작성**

아래 내용을 그대로 작성한다.

```markdown
# AGENTS.md

> EDDR의 문서 워크플로우 규약. 에이전트는 작업 시작 시 이 파일과 `wiki/WIKI_INDEX.md`를 읽는다.
> 설계 근거: `docs/SECOND_BRAIN_DESIGN.md`.

## 1. 3-Layer 문서 모델

| Layer | 파일 | 소유 | 로드 |
|---|---|---|---|
| **Schema** | `CLAUDE.md`, `CONTEXT.md`, `AGENTS.md`, `wiki/WIKI_INDEX.md` | 인간/공용 | 항상 |
| **Wiki** | `wiki/` 아래 topic별 markdown | LLM(에이전트) | index 보고 on-demand |
| **Source** | `docs/PLAN.md`, `docs/adr/`, `docs/SOLUTION_REVIEW.md`, `docs/01_eda_findings.md` | 인간 | 읽기전용, 필요 시 drill-down |

## 2. 권위 규칙 (중요)

- **Source > Wiki**: 충돌 시 Source가 맞고 wiki를 수정한다.
- **Source가 outdated면 Source부터 고친 뒤 wiki를 갱신**한다. wiki가 source를 우회해 사실상 SoT가 되는 것을 금지.

## 3. Wiki Page Frontmatter 규격

​```yaml
---
title: "..."
source: ["docs/adr/0001-privacy-boundary.md", "docs/PLAN.md#D6"]
last_verified: 2026-05-31
status: fresh        # fresh | verified | stale | archived
confidence: high     # high | medium | low
tags: [privacy, pii]
---
​```

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
```

- [ ] **Step 2: 검증 — 파일 존재 + 핵심 섹션 포함**

Run: `test -f AGENTS.md && grep -c '^## ' AGENTS.md`
Expected: 출력 `6` (섹션 6개: 3-Layer/권위/frontmatter/Lifecycle/3 Operation/INDEX 분리)

Run: `grep -E 'Source > Wiki|QUERY|INGEST|LINT' AGENTS.md`
Expected: 4개 키워드 모두 매칭

---

### Task 2: PLAN.md — ADR-0004 반영 + 규모 정정 (Source 먼저)

**Files:**
- Modify: `docs/PLAN.md`

- [ ] **Step 1: PLAN.md 전체 Read**

Run(에이전트): `docs/PLAN.md`를 Read하여 D8 행(약 L46), D10 행(약 L48), §4.1 스키마(`near_duplicate_group_id`·`persons`/`photo_persons`, 약 L82·L98–105), §4.2 near-dup 규칙(약 L132–133), 골든셋/§10(약 L243–245), 규모 `~10만`/`~10万` 등장 위치를 확인한다. 아래 Edit의 old_string은 정확히 일치해야 하므로 실제 텍스트로 대조한다.

- [ ] **Step 2: 상단 배너 추가**

§1(문서 최상단 개요) 끝에 다음 한 줄을 삽입:

```markdown
> ⚠️ **ADR-0004 반영(2026-05-31)**: 본 문서의 D8(near-dup 그룹핑)은 **v1 보류**, D10(person 질의)은 **폐기**되었다. 컬럼·테이블·골든셋 분포의 영향은 각 위치 주석 및 `wiki/decisions/eda-scope.md` 참조.
```

- [ ] **Step 3: D8 결정로그 행 주석**

Edit old_string (Step 1에서 정확 대조):
```
| D8 | 인덱싱 사이클 | 1차 batch 후 점진적 업데이트 | content hash dedup |
```
new_string:
```
| D8 | 인덱싱 사이클 | 1차 batch 후 점진적 업데이트 | content hash dedup · near-dup 그룹핑은 **ADR-0004로 v1 보류** |
```

- [ ] **Step 4: D10 결정로그 행 주석**

Edit old_string:
```
| D10 | 인물 데이터 | Photos.app Persons named만 import | photos_person_uuid 보존 |
```
new_string:
```
| D10 | 인물 데이터 | Photos.app Persons named만 import | photos_person_uuid 보존 · **person 질의는 ADR-0004로 폐기**(데이터 적재는 유지) |
```

- [ ] **Step 5: §4.2 near-dup 규칙 주석**

Edit old_string:
```
- BLAKE3 다름 + dHash 한 단위 차이 → `near_duplicate_group_id`로 묶음, UI는 그룹 당 1장 노출
```
new_string:
```
- ~~BLAKE3 다름 + dHash 한 단위 차이 → `near_duplicate_group_id`로 묶음, UI는 그룹 당 1장 노출~~ → **v1 보류(ADR-0004)**: near-dup 미처리, 중복 허용
```

- [ ] **Step 6: 스키마 컬럼/테이블 주석**

Step 1에서 확인한 §4.1 위치에서:
- `near_duplicate_group_id` 컬럼 정의 줄 끝에 ` — v1 미사용(ADR-0004 보류)` 추가
- `persons`/`photo_persons` 테이블 헤더 줄에 ` — v1: 데이터 적재만, 질의 폐기(ADR-0004)` 추가

(정확한 old_string은 Read로 확인 후 적용. 삭제하지 말고 주석만 덧붙인다.)

- [ ] **Step 7: 골든셋 R2 + 규모 주석**

- 골든셋 분포(§10 부근, `R1 5 / R2 3 / R3 2`)에 ` — R2(person)는 ADR-0004로 재정의 필요(TODO.md)` 추가
- `~10만 장`/`~10万 장` 등장 위치를 ` ~10만 장(실측 9,047, EDA 기준)`으로 정정

- [ ] **Step 8: 검증 — 주석이 반영되었는지**

Run: `grep -c 'ADR-0004' docs/PLAN.md`
Expected: `5` 이상 (배너+D8+D10+§4.2+스키마/골든셋)

Run: `grep -E '9,047|9047' docs/PLAN.md`
Expected: 규모 정정 줄 매칭

---

### Task 3: wiki/decisions/ — 결정 5 페이지

**Files:**
- Create: `wiki/decisions/privacy.md`, `wiki/decisions/photo-identity.md`, `wiki/decisions/tool-surface.md`, `wiki/decisions/eda-scope.md`, `wiki/decisions/decision-log.md`

각 페이지: 아래 frontmatter를 그대로 + 명시 source를 Read하여 "필수 사실"을 본문으로 컴파일.

- [ ] **Step 1: privacy.md** — source `docs/adr/0001-privacy-boundary.md` Read 후 작성

```markdown
---
title: "Privacy 경계"
source: ["docs/adr/0001-privacy-boundary.md", "docs/PLAN.md#D6"]
last_verified: 2026-05-31
status: fresh
confidence: high
tags: [privacy, pii, llm-tool]
---
```
필수 사실(본문): 이미지 바이너리·정밀좌표(lat/lng)·카메라 serial 등 PII EXIF는 외부 LLM에 **절대 전송 안 함** / 위치는 country/city/district까지만 / Photos hidden 사진은 **인덱싱 단계부터 제외** / `latitude`·`longitude`는 로컬 거리계산 전용, tool 응답 schema에 미포함 / 응답 schema가 이 경계를 자동 강제.

- [ ] **Step 2: photo-identity.md** — source `docs/adr/0002-photo-identity.md` Read 후 작성

```markdown
---
title: "Photo 정체성"
source: ["docs/adr/0002-photo-identity.md", "docs/PLAN.md#D16"]
last_verified: 2026-05-31
status: fresh
confidence: high
tags: [photo, identity, dedup]
---
```
필수 사실: Photos.app asset 1개 = `photos` 1행(정체성 SoT) / 원본+보정본 = 1 photo(variant 미보존) / Burst는 keeper만 / Live Photo는 정지 이미지만 / `source_uri` = Photos UUID 또는 로컬 절대경로 / dedup은 cross-source 중복만 처리.

- [ ] **Step 3: tool-surface.md** — source `docs/adr/0003-llm-tool-surface.md` Read 후 작성

```markdown
---
title: "LLM Tool Surface (5개)"
source: ["docs/adr/0003-llm-tool-surface.md", "docs/PLAN.md#D21"]
last_verified: 2026-05-31
status: fresh
confidence: high
tags: [llm-tool, api, yagni]
---
```
필수 사실: tool 정확히 5개 — `search_photos`, `semantic_search_photos`, `list_trips`, `get_trip`, `get_photo` / **freeform SQL 없음** / 모든 list 응답은 `limit` 강제(context overflow 차단) / 응답 schema가 Privacy 경계를 자동 강제 / 새 tool은 골든셋이 요구할 때만(YAGNI). (각 tool 시그니처는 ADR-0003 Read로 정확히 옮긴다.)

- [ ] **Step 4: eda-scope.md** — source `docs/adr/0004-eda-driven-scope-decisions.md` Read 후 작성

```markdown
---
title: "EDA 후속 스코프 결정 (D8 보류·D10 폐기)"
source: ["docs/adr/0004-eda-driven-scope-decisions.md", "docs/01_eda_findings.md"]
last_verified: 2026-05-31
status: fresh
confidence: high
tags: [eda, scope, near-dup, person]
---
```
필수 사실: **D8 near-dup 보류** — EDA에서 발견된 93쌍이 전부 export-artifact 복사본(Hamming distance 0)이라 실제 라이브러리 near-dup율 미측정 → v1은 중복 허용 / **D10 person 질의 폐기** — named person 1명, INDEXABLE의 12.3%에만 등장 → R2 person-query recall 구조적 불가 / person *데이터 적재*는 유지하되 *질의 기능*만 폐기.

- [ ] **Step 5: decision-log.md** — source `docs/PLAN.md` §3(D1–D23) Read 후 작성

```markdown
---
title: "결정 로그 D1–D23 (압축)"
source: ["docs/PLAN.md#3"]
last_verified: 2026-05-31
status: fresh
confidence: high
tags: [decisions, log]
---
```
필수 사실: PLAN.md §3의 D1–D23을 [ID | 주제 | 결정 | 비고] 표로 압축. ADR화된 4건(privacy=D6, photo-identity=D16, tool-surface=D21, eda-scope=D8·D10)은 각각 `decisions/{privacy,photo-identity,tool-surface,eda-scope}.md`로 **cross-link**. 주요 비-ADR 결정 명시: D4(iCloud/Photos가 사진 SoT, EDDR은 파생만), D19(caption v1 영어 1개), D20(임베딩 image+caption_text 2벡터). D8·D10은 "ADR-0004로 보류/폐기"로 표기.

- [ ] **Step 6: 검증 — 5개 파일 + frontmatter**

Run: `ls wiki/decisions/ | wc -l`
Expected: `5`

Run: `for f in wiki/decisions/*.md; do echo "== $f"; head -1 "$f"; grep -c '^source:\|^status:\|^last_verified:' "$f"; done`
Expected: 각 파일 첫 줄 `---`, frontmatter 필드 매칭 ≥3

---

### Task 4: wiki/architecture/ — 설계 요약 3 페이지

**Files:**
- Create: `wiki/architecture/db-schema.md`, `wiki/architecture/indexing-pipeline.md`, `wiki/architecture/query-flow.md`

- [ ] **Step 1: db-schema.md** — source `docs/PLAN.md` §4 Read 후 작성

```markdown
---
title: "DB 스키마 요약"
source: ["docs/PLAN.md#4"]
last_verified: 2026-05-31
status: fresh
confidence: high
tags: [schema, sqlite, architecture]
---
```
필수 사실: 단일 SQLite + `sqlite-vec`. 핵심 테이블 — `photos`, `embeddings`(사진당 image+caption_text 2개), `captions`, `persons`/`photo_persons`, `trips`/`trip_countries`, `daily_radius_areas`, `geocode_cache`. 각 테이블의 주요 컬럼·관계를 PLAN §4.1 기준으로 옮김. **ADR-0004 표기**: `near_duplicate_group_id`(v1 미사용), `persons`/`photo_persons`(v1 데이터만, 질의 폐기). 말미에 "**코드 진화 시 코드 기준으로 갱신**" 명시.

- [ ] **Step 2: indexing-pipeline.md** — source `docs/PLAN.md` §5 Read 후 작성

```markdown
---
title: "인덱싱 파이프라인"
source: ["docs/PLAN.md#5"]
last_verified: 2026-05-31
status: fresh
confidence: high
tags: [indexing, pipeline, architecture]
---
```
필수 사실: 단계 순서 — osxphotos 메타·경로·persons 추출 + 로컬 폴더 스캔 → BLAKE3/dHash 해시 & cross-source dedup → reverse geocode(Nominatim 1req/s + 캐시) → Daily Radius 추정(KDE) → 로컬 Vision(image embedding + 영어 caption + caption text embedding) → Trip 클러스터링 → SQLite upsert. **Recent-first**(최근 1년 우선 batch 후 백그라운드 continue), 각 단계 `photos.indexing_status` 체크포인트로 중단·재실행 시 skip.

- [ ] **Step 3: query-flow.md** — source `docs/PLAN.md` §6 Read 후 작성

```markdown
---
title: "질의/답변 흐름"
source: ["docs/PLAN.md#6"]
last_verified: 2026-05-31
status: fresh
confidence: high
tags: [query, gradio, claude, architecture]
---
```
필수 사실: Gradio 채팅 UI → Claude API → 5 structured tool → Claude가 한국어·친근한 톤 답 생성 → Gradio가 답변 텍스트 + 로컬 path 사진 그리드 렌더. 답변 footer에 "N/M 사진 인덱싱됨" 표시(부분 인덱싱 인지). Privacy 보장 경로(tool 응답에 PII·좌표 없음).

- [ ] **Step 4: 검증**

Run: `ls wiki/architecture/ | wc -l`
Expected: `3`

Run: `grep -l 'ADR-0004' wiki/architecture/db-schema.md`
Expected: `wiki/architecture/db-schema.md` (스키마 페이지에 ADR-0004 표기 존재)

---

### Task 5: wiki/models/ + data-profile/ + research/ + impl-log/

**Files:**
- Create: `wiki/models/model-decisions.md`, `wiki/data-profile/eda-findings.md`, `wiki/research/context-engineering.md`, `wiki/impl-log/_index.md`

- [ ] **Step 1: model-decisions.md** — source `docs/SOLUTION_REVIEW.md` Read 후 작성

```markdown
---
title: "모델 선택 결정 추적"
source: ["docs/SOLUTION_REVIEW.md", "docs/PLAN.md#7"]
last_verified: 2026-05-31
status: fresh
confidence: medium
tags: [models, vision, embedding, pending]
---
```
필수 사실: 표 [영역 | 현행(PLAN §7) | 권고(SOLUTION_REVIEW) | 우선순위 | status]. **전 항목 status = `pending`**, 결정 메모 "A/B는 Vision 단계(빌드순서 ⑤)에서 골든셋으로". 항목:
- caption: Qwen2.5-VL 7B → **Qwen3-VL 8B**(+Gemma 4 26B MoE 후보) · P1 · pending
- text embedding: BGE-M3 → **Qwen3-Embedding-8B**(MTEB +7.6p) · P1 · pending
- image embedding: 3모델/2벡터 → **Qwen3-VL-Embedding 8B 통합**(fallback SigLIP 2 / Jina-CLIP v2) · P2 · pending
- dHash cutoff 재튜닝 · HDBSCAN(Daily Radius) · 규모 9,047 정정 · P3 · pending
말미: "이 page가 SOLUTION_REVIEW 권고의 *수락/거부 추적*을 담당(원본은 불변)."

- [ ] **Step 2: eda-findings.md** — source `docs/01_eda_findings.md` Read 후 작성

```markdown
---
title: "EDA 실측 핵심 수치"
source: ["docs/01_eda_findings.md", "notebooks/01_eda.ipynb"]
last_verified: 2026-05-31
status: fresh
confidence: high
tags: [eda, data-profile, metrics]
---
```
필수 사실: 총 9,047 assets / INDEXABLE 8,574(94.8%) / GPS 좌표 91% / `taken_at` 유효 100% / near-dup 93쌍 전부 Hamming 0(export artifact) / named person 1명, INDEXABLE의 12.3% / Daily Radius 클러스터 존재 확인 / trip 후보 44개 감지 / 스코프: 메타데이터 한정(Vision·픽셀·iCloud EDA는 별도 세션). 결과 결정은 `wiki/decisions/eda-scope.md` 참조.

- [ ] **Step 3: context-engineering.md** — source `docs/SECOND_BRAIN_DESIGN.md` §5·§7 Read 후 작성

```markdown
---
title: "Context Engineering & LLM Wiki 패턴"
source: ["docs/SECOND_BRAIN_DESIGN.md#5", "docs/SECOND_BRAIN_DESIGN.md#7"]
last_verified: 2026-05-31
status: fresh
confidence: medium
tags: [research, context-engineering, llm-wiki]
---
```
필수 사실: 학술 근거 표 — CodeDelegator(ephemeral-persistent 분리), Anthropic Context Engineering(5원칙), HiRAG(계층 검색), Context Rot/Morph(길이↑→성능↓), Memory for LLM Agents(write-manage-read), Complexity Trap(단순 masking). 구현체 비교 — Karpathy LLM Wiki(인프라 0, 채택 기반), Pratiyush(MCP, 참조만), rohitg00 agentmemory(과도), LLM Wiki v2(lifecycle만 채택), OmegaWiki(부적합). **EDDR 선택: Karpathy 원본 + lifecycle 4단계.**

- [ ] **Step 4: impl-log/_index.md (stub)**

```markdown
---
title: "구현 로그 (인덱스)"
source: []
last_verified: 2026-05-31
status: fresh
confidence: low
tags: [impl-log, stub]
---

# 구현 로그

구현 착수(빌드순서 ②) 후 이슈·해결·학습을 page별로 기록한다. 현재 코드 0행 — stub.
INGEST 시점: 모듈 구현 완료마다 `wiki/impl-log/<topic>.md` 추가 + 본 인덱스·`WIKI_INDEX.md` 갱신.
```

- [ ] **Step 5: 검증**

Run: `find wiki/models wiki/data-profile wiki/research wiki/impl-log -name '*.md' | wc -l`
Expected: `4`

Run: `grep -c 'pending' wiki/models/model-decisions.md`
Expected: `4` 이상 (전 항목 pending 표기)

---

### Task 6: wiki/WIKI_INDEX.md — 전체 목차

**Files:**
- Create: `wiki/WIKI_INDEX.md`

- [ ] **Step 1: WIKI_INDEX.md 작성** (Task 3~5 완료 후, 12 페이지 전부 존재해야 함)

```markdown
# WIKI_INDEX

> wiki/ 전체 목차. 작업 시작 시 먼저 읽고 관련 page만 로드한다. 프로토콜: `AGENTS.md`.
> 200행 초과 시 디렉터리별 하위 INDEX로 분리.

## decisions/ — 결정의 컴파일된 요약
- [privacy.md](decisions/privacy.md) — Privacy 경계: PII·이미지·정밀좌표 외부 LLM 전송 금지 (ADR-0001)
- [photo-identity.md](decisions/photo-identity.md) — Photos asset 1=1행, dedup=cross-source만 (ADR-0002)
- [tool-surface.md](decisions/tool-surface.md) — LLM tool 정확히 5개, freeform SQL 없음 (ADR-0003)
- [eda-scope.md](decisions/eda-scope.md) — D8 near-dup 보류·D10 person 질의 폐기 (ADR-0004)
- [decision-log.md](decisions/decision-log.md) — D1–D23 전체 결정 압축

## architecture/ — 스키마·파이프라인·흐름
- [db-schema.md](architecture/db-schema.md) — SQLite 테이블 인벤토리 (PLAN §4)
- [indexing-pipeline.md](architecture/indexing-pipeline.md) — 인덱싱 파이프라인 7단계 (PLAN §5)
- [query-flow.md](architecture/query-flow.md) — Gradio→Claude→5tool→답변 흐름 (PLAN §6)

## models/ — 모델 선택 추적
- [model-decisions.md](models/model-decisions.md) — SOLUTION_REVIEW 권고 status (전부 pending, A/B는 Vision 단계)

## data-profile/ — 실측 데이터
- [eda-findings.md](data-profile/eda-findings.md) — 9,047 assets EDA 핵심 수치

## research/ — 외부 근거
- [context-engineering.md](research/context-engineering.md) — context pollution 연구·LLM Wiki 패턴 비교

## impl-log/ — 구현 기록
- [_index.md](impl-log/_index.md) — (stub) 구현 착수 후 충전
```

- [ ] **Step 2: 검증 — 모든 page가 등재되고 링크가 실재하는지**

Run: `wc -l wiki/WIKI_INDEX.md`
Expected: 200행 미만

Run(누락·orphan 점검):
```bash
diff <(grep -oE '\]\(([a-z/_-]+\.md)\)' wiki/WIKI_INDEX.md | sed -E 's/\]\(|\)//g' | sort) \
     <(cd wiki && find . -name '*.md' ! -name 'WIKI_INDEX.md' | sed 's|^\./||' | sort)
```
Expected: 출력 없음(INDEX 링크 집합 = 실제 page 집합). 차이가 있으면 INDEX 또는 파일을 맞춘다.

---

### Task 7: CLAUDE.md — 포인터형 리팩터링

**Files:**
- Modify: `CLAUDE.md` (55행 full-text → ~35행 포인터형)

- [ ] **Step 1: 현재 CLAUDE.md Read** — 프로젝트 개요·현재상태 단락을 verbatim 보존 대상으로 확인.

- [ ] **Step 2: CLAUDE.md 전체 교체 작성**

아래로 전체 내용을 교체한다. (개요/현재상태 단락은 기존 표현 유지, 나머지는 포인터화. `~10만 장`은 프로젝트 소개 표현이므로 유지 — 규모 정정은 PLAN.md 책임.)

```markdown
# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## 프로젝트 개요

**EDDR (어디더라?)** — 내 사진(~10만 장)의 메타데이터·이미지 분석 결과를 로컬 SQLite로 인덱싱하고, 한국어 자연어 질문에 Claude가 tool use로 "언제·어디서·누구랑·뭘 했는지"를 답하는 **개인용·로컬·단일 사용자** 사진 챗봇. macOS 전용 (Photos Library + 로컬 vision).

**현재 상태**: 설계 문서만 존재하고 코드는 아직 없다. 설계·ADR은 git에 커밋됨.

## 문서 체계 (세션 시작 시)

3-layer 문서 체계를 쓴다. 상세 프로토콜은 **`AGENTS.md`**.
- **Schema** (항상 로드): `CLAUDE.md`, `CONTEXT.md`, `AGENTS.md`, `wiki/WIKI_INDEX.md`
- **Wiki** (컴파일된 지식, on-demand): `wiki/` — 먼저 `wiki/WIKI_INDEX.md` 읽고 관련 page만 로드
- **Source** (권위 원본, 읽기전용): `docs/PLAN.md`, `docs/adr/`, `docs/SOLUTION_REVIEW.md`

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
```

- [ ] **Step 3: 검증 — 행 수 축소 + 4중 중복 제거 + 링크 유효**

Run: `wc -l CLAUDE.md`
Expected: ~35행(±5). 55행 대비 축소.

Run: `grep -c 'wiki/decisions/' CLAUDE.md`
Expected: `5` (불변규칙 4 + decision-log 1, 포인터화 확인)

Run(불변규칙 full-text 잔존 없는지 — 예: 5 tool 이름 나열이 사라졌는지):
`grep -c 'semantic_search_photos' CLAUDE.md`
Expected: `0` (tool 이름은 이제 wiki에만; CLAUDE.md는 링크만)

---

### Task 8: 초기 LINT self-check (통합 회귀)

**Files:** 없음(검증 전용). AGENTS.md §5 LINT 절차를 수동 실행.

- [ ] **Step 1: 전 page frontmatter 필수 필드 검사**

Run:
```bash
for f in $(find wiki -name '*.md' ! -name 'WIKI_INDEX.md'); do
  for k in title source last_verified status confidence tags; do
    grep -q "^$k:" "$f" || echo "MISSING $k in $f";
  done
done
```
Expected: 출력 없음(impl-log/_index.md 포함 12 page 모두 6필드 보유).

- [ ] **Step 2: source 경로 실재 검증**

Run:
```bash
grep -rhoE 'docs/[A-Za-z0-9._/-]+\.md|docs/adr/[A-Za-z0-9._/-]+\.md' wiki --include='*.md' \
  | sed -E 's/#.*//' | sort -u | while read p; do test -f "$p" || echo "BROKEN source: $p"; done
```
Expected: 출력 없음(모든 frontmatter `source` 원본 실재).

- [ ] **Step 3: WIKI_INDEX 완전성** — Task 6 Step 2의 diff 재실행, 출력 없음 확인.

- [ ] **Step 4: 내용 정확성 spot-check (수동)**

3개 page를 source와 대조: `eda-findings.md`의 9,047/8,574/12.3% 숫자가 `docs/01_eda_findings.md`와 일치하는가? `tool-surface.md`의 5 tool 이름이 `docs/adr/0003-llm-tool-surface.md`와 일치하는가? `model-decisions.md`의 모델명이 `docs/SOLUTION_REVIEW.md`와 일치하는가? 불일치 발견 시 wiki page 수정(source 우선).

- [ ] **Step 5: LINT 리포트**

위 1~4 결과를 요약 보고. 불일치 0이면 "전 page fresh·source trace 확인". 잔여 항목 있으면 목록화.

---

### Task 9: Commit (사용자 명시 요청 시에만)

**Files:** 없음. **이 작업은 사용자가 "commit해줘"라고 할 때만 실행한다.**

- [ ] **Step 1: 사용자에게 commit 범위 확인**

기존 미커밋 변경(`TODO.md`, `docs/SECOND_BRAIN_DESIGN.md`, `docs/images/`)을 포함할지, 본 작업 산출물만 커밋할지 묻는다.

- [ ] **Step 2: (승인 시) 논리 단위 커밋**

본 작업 산출물만 커밋하는 예시(2 커밋):
```bash
# (a) Schema/Source 레이어
git add AGENTS.md CLAUDE.md docs/PLAN.md docs/superpowers/
git commit -m "docs: second-brain schema layer — AGENTS.md, CLAUDE.md 포인터화, PLAN.md ADR-0004 반영"

# (b) Wiki 레이어
git add wiki/
git commit -m "docs: second-brain wiki layer — 12 페이지 INGEST + WIKI_INDEX"
```
(단일 커밋 선호 시 한 번에 `git add` 후 커밋.)

---

## Self-Review (작성자 점검 결과)

**1. Spec coverage** — spec §4 인벤토리의 모든 파일이 Task에 매핑됨: AGENTS.md(T1), PLAN.md(T2), decisions 5(T3), architecture 3(T4), models/data-profile/research/impl-log(T5), WIKI_INDEX(T6), CLAUDE.md(T7). spec §5 규약 → AGENTS.md 본문(T1). spec §9 Done 기준 → T8 LINT가 검증. **gap 없음.**

**2. Placeholder scan** — wiki page 본문은 "필수 사실 나열 + source Read"로 구체화(작업 방식 메모에 근거 명시). impl-log는 *의도적* stub(spec default #3). "TBD/TODO(미정)" 없음.

**3. Type/이름 일관성** — 파일 경로·frontmatter 필드(title/source/last_verified/status/confidence/tags)가 T1 규격과 T3~T5 사용처에서 동일. WIKI_INDEX 링크 경로가 T3~T5 생성 경로와 일치. CLAUDE.md 링크 5개가 decisions/ 실제 파일명과 일치.

**4. 순서 정합** — T2(PLAN.md)가 T3~T5(wiki INGEST)보다 앞 → §5.4 권위규칙 준수. T6(INDEX)·T7(CLAUDE 링크)는 page 생성 후. T8 LINT가 최후.

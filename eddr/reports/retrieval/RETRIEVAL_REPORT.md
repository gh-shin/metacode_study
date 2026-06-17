# 검색 품질 개선 최종 리포트 — RRF·Reranker 검토 (2026-06-11)

> 요청: "RRF와 reranker를 도입하여 검색 품질을 더 끌어올릴 수 있을지" — 1(recall 픽스)
> → 2(RRF) → 3(reranker) 점진 진행, 단계마다 baseline 대비 실측. 실험 원장:
> `experiments.jsonl`(10 runs) · 비교표: `RESULTS.md` · 도구: `scripts/bench_retrieval.py`.

## TL;DR

| 항목 | 판정 | 근거 (k-정규화 recall, 8문항 평균) |
|---|---|---|
| **Stage 1** adaptive over-fetch | **채택** | 0.378 → 0.578 — filter starvation 해소(G02 2→16장) |
| **Stage 1** 질의 instruction(qwen3-embedding 권장) | **채택** | 0.578 → 0.64 — 임베딩 순위 자체 개선(diag@500 0.645→0.733) |
| **Stage 2** RRF(FTS5 BM25 융합) | **기각** | 0.64 → 0.62 — 광범위 키워드가 노이즈 주입(G05·G06 하락) |
| **Stage 2** 필터 의미론 가이드(trip_id 유도) | **채택** | 0.64 → **0.739** — G03 천장 3→18 (구조 발견, 아래) |
| **Stage 3** cross-encoder reranker(bge-reranker-v2-m3) | **기각** | 0.739 → 0.689 — G10 20→10 반토막(ko×en 변별력 부족) |

**최종 구성(stage2-final)은 baseline 대비 약 2배(0.378→0.739).** 정작 요청의 두 기법
(RRF·reranker)은 실측에서 모두 손해였고, 효과는 전부 *후보 생성(recall)과 필터 의미론*
픽스에서 나왔다 — 최초 진단("측정된 실패는 ranking이 아니라 recall") 그대로.

E2E 골든셋(ollama qwen3.6:27b no-think)도 동일 방향: G02 4→50장, G03 은하수 1~5→20장
(trip 경로·distractor 회피), G09 1→20장(동음이의 구분), G10 위치무 구분 언급 등장.
최종 E2E: `reports/golden/20260611_1233_*.md` (채점은 이 리포트 기준 권장).

## 측정 체계

- **마이크로벤치**(`scripts/bench_retrieval.py`): LLM 없이 검색 레이어만. 골든셋 8문항의
  ground truth를 실DB SQL로 재현(시작 시 카운트 검증), 2층 측정 —
  ① production 경로(`semantic_search_photos`) 최종 recall@k ② 전역 임베딩 순위 진단
  (diag@100/500/2000, 파이프라인 설정 무관). run당 ~40초·무비용이라 변형마다 즉시 A/B.
- **E2E 골든셋**(`eddr golden --backend ollama --no-think`, ~20분): tool 선택·프롬프트
  준수까지 포함한 종단 검증. 마이크로벤치 채택분만 E2E로 확정.
- **한계(정직 고지)**: ① GT가 캡션 LIKE 기반 proxy라 절대값이 아닌 상대 비교용이며,
  특히 lexical(RRF) 평가는 GT 정의와 순환해 *유리하게* 편향됨 — 그런데도 손해로 측정된
  것이 기각의 강한 근거. ② `rrf`(12:23) run은 FTS 인덱스가 빈 상태로 돈 무효 측정
  (아래 사건 기록) — `rrf-fixed`가 유효본. ③ G05는 GT가 출처 폴더 21장로 좁지만 실제
  정답은 라이브러리 전체 봄꽃(E2E에서는 통과 수준) — norm 0.1은 proxy 과소평가.

## Stage 1 — recall 픽스 (채택, 커밋 `f4c4068`)

**진단**: 고정 k×5 over-fetch 절단이 필터 질의에서 후보 고갈을 일으킴 — G02(아이슬란드
도로)는 130장 모집단에서 2장 반환. 전역 top-2000 진단으로 GT의 91~100%가 임베딩 순위
안에 있음을 확인 → 절단이 원인, 임베딩은 무죄.

1. **adaptive over-fetch**: 필터 통과 < k면 풀을 ×5씩 확대 재질의(스토어 소진 시 중단).
   9,383벡터 코퍼스라 최심 조회도 ms 단위. G02 2→16, G09 4→18, G01 12→20.
2. **질의 instruction**: qwen3-embedding 권장 형식(`Instruct: …\nQuery:{query}`,
   질의 측 전용·문서 측 불변·영어)을 `QueryService` 기본값으로. MTEB 기본 instruction이
   diag@500 +0.088; 도메인 특화 변형은 G02 붕괴(0건)로 기각 — 분산이 큼.

## Stage 2 — RRF 기각, 대신 필터 의미론 가이드 채택 (커밋 `84051dc`)

**RRF 구현**: captions FTS5(external content·porter) + BM25 → `keywords`(영어) 파라미터
→ RRF(K=60) 융합. 실측 3변형 모두 손해 또는 무효과:
전역 lexical은 temple·flower 같은 광범위 키워드가 필터 밖 후보를 융합 상위로 밀어
G05 2→1·G06 1→0(−), 필터 스코프·trip 스코프 변형도 한계효용 0. **LLM tool 스키마에서
비노출 처리**(파라미터·FTS·`--rrf` 벤치 경로는 재현용 유지). 재도입 조건: 정밀 고유명사
어휘가 캡션에 충분해질 때(예: OCR·지명 enrich 후).

**부수 사건 — 빈 인덱스 무효 측정**: external-content FTS는 `count(*)`가 content
테이블을 그대로 비춰 rebuild 감지가 무효 → 실색인 0건으로 1회 측정(12:23 `rrf` 행).
docsize shadow 테이블 기준으로 수정 + 회귀 테스트 추가 후 재측정(`rrf-fixed`).

**진짜 발견 — 필터 의미론 천장**: G03(몽골 은하수) GT 19장 중 `country='몽골'`
geocode는 **3장뿐**(GPS 무 16장) — `countries` 필터로는 만년 3장이 구조적 상한이었다.
**trip 배정은 시간 기반이라 GPS 무관** → `trip_id` 필터로 3→18/19 (6배). G02도 천장
75/130 → 130. 코드가 아니라 가이드 문제(G04와 동일 패턴)라 tool description·시스템
프롬프트에 "여행 결부 질의는 list_trips→trip_id" 명시로 해소. **E2E에서 LLM이 실제로
이 경로를 채택**(G02·G03 모두 list_trips→trip_id 호출 확인).

## Stage 3 — reranker 기각 (커밋 `b01d471`)

bge-reranker-v2-m3(cross-encoder, sentence-transformers·MPS)를 필터 통과 상위 100에
주입식 적용(`QueryService(reranker=…)`, 기본 비활성). 실측: G02·G09 +1장 vs
**G10 20→10 반토막** — 한국어 질의 × 영어 캡션 쌍에서 변별력이 qwen3-embedding 임베딩
순위보다 낮음(사전 스모크의 빈약한 절대점수 0.016과 정합). 질의당 +0.6~2.9s 지연,
torch 스택 의존(GB 단위)까지 감안해 기각. 의존성은 `.venv` ad-hoc으로만 설치
(pyproject 미기재 — production 무흔적). 재도입 조건: 캡션 한국어화 또는 ko-en
cross-encoder 품질 개선 + "풀 내 순서 실패"가 채점에서 실제 관측될 때.

## 남은 약점과 후속 후보 (이번 범위 밖)

- **G06(개심사·GPS 무·캡션에 이름 없음)**: 검색기로 못 고치는 데이터 부재 부류.
  후속 후보 — local/takeout 폴더명 lexical 인덱싱, 이미지 직접 임베딩 leg(TODO D20).
  단 E2E에서는 LLM 질의 확장이 서산 신창리(개심사 소재지) 후보까지 도달 — 채점 관찰.
- **G05 proxy 과소평가**: E2E 채점으로 판단(벤치 norm은 무시 가능).
- 기존 TODO 연동: persons 명세·날짜 타임존 정책(사용자 결정 대기)은 본 작업과 독립.

## 재현

```bash
uv run python scripts/bench_retrieval.py --gt-only          # GT 카운트 검증
uv run python scripts/bench_retrieval.py --label <name>     # 현 구성 측정
#   --instruct 'none'|템플릿  --rrf  --rerank(요 .venv ad-hoc sentence-transformers,
#   uv pip install 후 uv run --no-sync로 실행 — uv run이 lock 버전을 복원함)
uv run eddr golden --backend ollama --no-think               # E2E (~20분)
```

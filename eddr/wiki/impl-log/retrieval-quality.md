---
title: "검색 품질 개선 — RRF·reranker 검토와 recall 픽스"
source: ["reports/rag_quality/ASSIGNMENT_REPORT.md", "reports/rag_quality/retrieval/20260622_full_matrix/experiments.jsonl", "scripts/bench_retrieval.py"]
last_verified: 2026-06-23
status: fresh
confidence: high
tags: [retrieval, semantic-search, benchmark, rrf, reranker, query]
---

# 검색 품질 개선 (2026-06-11)

사용자 요청("RRF·reranker로 검색 품질을 끌어올릴 수 있을까")을 1→2→3 점진 실측으로
검토. **상세·수치·재현법의 SoT는 `reports/retrieval/RETRIEVAL_REPORT.md`**(10 runs
원장 `experiments.jsonl`). 커밋: `a1d9b3f`(벤치) `f4c4068`(Stage1) `188c802`(E2E)
`84051dc`(Stage2) `b01d471`(Stage3).

## 결론 — 채택 2 · 기각 2 (k-정규화 recall 평균 0.378 → 0.739)

- **채택**: ① adaptive over-fetch(필터 통과<k면 풀 ×5 확대 — filter starvation 해소,
  G02 2→16장) ② qwen3-embedding 질의 instruction 기본 적용(질의 측 전용, diag +0.088)
  ③ **필터 의미론 가이드** — countries/cities는 geocode 기반이라 GPS 무 사진이 원천
  탈락(G03 GT 19장 중 몽골 geocode 3장 = 구조적 천장). trip 배정은 시간 기반이라
  trip_id 필터로 3→18 (6배). tool description·시스템 프롬프트로 유도, E2E에서 LLM이
  실제 채택 확인.
- **기각/제한 채택**: 전체 RRF(FTS5 BM25 융합)는 광범위 키워드 노이즈 때문에 기각.
  다만 2026-06-22 후속에서 precise lexical leg는 유지하고 `food`·`temple`·`flower`·`travel`
  같은 broad keyword만 낮은 가중치(0.25)로 제한 채택했다. cross-encoder reranker는
  bge-reranker-v2-m3의 ko질의×en캡션 변별력 부족(G10 반토막)으로 계속 비활성.

## 만든 것

- `scripts/bench_retrieval.py` — retrieval 마이크로벤치(골든셋 GT를 SQL로 재현·검증,
  production recall@k + 전역 임베딩 순위 진단 2층). run당 ~40초 무비용 A/B.
- `captions_fts`(FTS5 external content·porter) + `search_caption_photo_ids` —
  repository에 잔존(기각된 RRF의 인프라지만 lexical 디버깅에 유효). 함정 2건 기록:
  bm25()는 플래트닝 시 불법 컨텍스트(MATERIALIZED CTE 배리어), external content의
  count(*)는 content를 비춰 rebuild 감지는 docsize shadow 기준이어야 함.
- `QueryService` 확장: `query_embed_template`(기본 instruction)·`reranker`(기본 None)·
  `keywords`(스키마 비노출) — 테스트 184 passed.

## 2026-06-22 후속 — broad keyword lexical 하향

TODO의 RAG 품질 개선 항목 중 broad keyword 가중 조정을 완료했다. 원인은 `food`·`temple`·
`flower`·`travel` 같은 DF 큰 단어가 lexical leg에서 vector leg와 같은 힘으로 RRF에 합류해
오캡션을 상위로 증폭하는 것이었다. 구현은 `QueryService.semantic_search_photos()` 내부에서
keyword를 precise/broad로 나누고, broad lexical leg만 `_BROAD_LEXICAL_WEIGHT = 0.25`로
합류시키는 최소 변경이다. precise keyword(`ruins` 등)의 boost와 note leg는 유지한다.

검증: `pytest tests/query/test_tools.py -q` 25 passed, `pytest tests/query/test_golden.py
tests/server/test_search.py -q` 23 passed, `uv run eddr golden --out /private/tmp/eddr-golden-broad-keyword-final`
PASS 10 / FAIL 0 / 보류 1(G06), report `20260622_0113_v2_search.md`.

## 2026-06-23 후속 — precision 기준 production 기본값 조정

RAG 과제 리포트에 precision을 추가하면서 단일 best 결론을 폐기했다. full matrix 기준
recall/coverage 최고는 `instruction ON · k=50 · RRF OFF`(`matrix-i1-k50-rrf0`,
mean recall norm 0.749, mean precision 0.557)이고, precision 최고는
`instruction ON · k=20 · RRF OFF`(`matrix-i1-k20-rrf0`, mean recall norm 0.732,
mean precision 0.725)다.

사용자가 precision best를 production에 반영하도록 요청해 `/api/search` 공용 코어
`run_search()`의 기본 검색 폭을 `k=50`에서 `k=20`으로 낮추고, `keywords_en`을
`semantic_search_photos()`에 전달하지 않도록 바꿨다. QueryService의 lexical/RRF 지원은
실험·fallback 인프라로 유지한다.

## E2E 영향 (ollama no-think, 채점 대기)

G02 4→50장 · G03 은하수 1~5→20장(trip 경로·운여해변 회피) · G09 1→20장(용산리
동음이의 구분) · G10 위치무 구분 언급 등장 · G06 포기→후보 제시. 최종 리포트
`reports/golden/20260611_1233_*` (사용자 채점은 이것 기준).

## 후속 (리포트 §남은 약점)

G06류 데이터 부재 → **D24 사용자 문답 enrichment로 방향 결정**(2026-06-11, PLAN §3):
날짜 기준 그룹 → 사용자 질문·답변 → 파생 데이터 업데이트, 검색 내부 불변. 빌드 타임
wizard(D15 패턴) 우선, 채팅 중 문답은 v2. 사용자 답변의 정밀 고유명사는 본문 RRF
재도입 조건과 맞물림. 폴더명 인덱싱·D20 image leg는 후순위 대안. 백로그: `TODO.md`.
uv 함정: ad-hoc 패키지 실험은 `uv pip install … && uv run --no-sync …`
(uv run이 lock 버전 복원).

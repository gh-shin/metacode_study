# G08 날짜질의 lane 재정렬 — 설계

- 날짜: 2026-06-15
- 상태: 승인됨 (브레인스토밍)
- 범위: RAG 품질 개선 트랙의 첫 sub-project — G08 날짜/사실 질의 라우터

## Context (왜)

RAG 품질 평가에서 E2E 골든 10문항 중 **G08만 FAIL**("이탈리아 언제 갔더라"). 원인: 모든 질의가
단일 `semantic_search_photos` 경로로 흐르고, KST 날짜 lane이 **관련도(rank)순**으로 정렬돼 trip
시작일(2019-06-29)이 상위 3 lane 밖으로 밀린다(상위는 07-11·06-30·07-07). 날짜/사실 질의는
관련도가 아니라 **시간 순서**가 답이어야 한다.

`docs/rag_quality/questions.yaml`의 G08 match = `date_lane_top: {date: "2019-06-29", within: 3}`.
이 규칙은 이미 존재하므로 자동 측정 가능(사용자 작성 대기 아님).

목표: fact 질의에서 trip 시작일 lane을 상위로 올려 **G08 PASS**(→ 골든 10/10), 나머지 9문항 비회귀.

## 비목표 (out of scope)

- 추출(`ExtractedQuery`) 스키마 확장·LLM 프롬프트 변경 — 프론트 `interpretation` 계약 보호.
- 사용자 공식 골든셋(`docs/golden_set.yaml`) 수정 — RAG 평가셋(`questions.yaml`)과 별개 셋이고
  match 보류는 사용자 몫.
- broad keyword 가중 조정·재캡션 RAG 수치화 — RAG 트랙의 다른 sub-project(후속).

## 설계

`server/routes/search.py` 국소 변경. **분류**와 **그룹핑**을 분리해 각각 독립 테스트 가능하게 한다.

### 1. `is_date_intent(query: str) -> bool` (신설)
명시적 시간 의문사만 매칭하는 순수 분류기. 정규식: `언제` · `몇\s*년(도)?` · `몇\s*월` · `며칠`.
"여행"·"사진" 등 일반어는 비매칭 — photo_list 질의(G01·G03·G07·G09) 회귀 차단의 핵심.

### 2. `group_by_kst_date(results, order_by_date: bool = False)` (인자 추가)
- `order_by_date=False`(기본): 현행 — lane을 그룹 최고 rank순 정렬(search.py:130). 비파괴.
- `order_by_date=True`: lane을 **날짜 오름차순**(가장 이른 날 = trip 시작일 top). `date=None`
  그룹은 말미.
- lane *내부* 사진 순서(rank 오름차순)는 두 경우 모두 유지 — 관련도 보존.

### 3. 배선 (호출부 2곳)
- route `search.py:86`: `group_by_kst_date(results, order_by_date=is_date_intent(query))`.
- golden 러너 `golden.py:250`: 동일하게 question 텍스트로 `is_date_intent`를 전달.
- `run_search` 시그니처는 **불변** — 라우팅(분류) 결정은 호출부 책임.

## 데이터 흐름

질의 → `run_search`(추출 → trip 스코프 → `semantic_search_photos`, **불변**) → 사진 결과 →
호출부가 `is_date_intent(query)` 판정 → `group_by_kst_date(results, order_by_date=…)` →
lane 정렬(fact면 날짜순). **사진 집합 자체는 불변, lane *순서*만 분기.**

## 테스트

- `is_date_intent` 단위: 양성("이탈리아 언제 갔더라"·"몇 년에 갔지")·음성("이탈리아 사진"·
  "바다 풍경"·"냉면 먹은 날").
- `group_by_kst_date(order_by_date=True)` 단위: 날짜 오름차순·`None` 말미·lane 내부 rank 유지.
  `order_by_date=False`는 현행 동등(회귀 가드).
- 회귀 사전점검: `questions.yaml` 비-fact 문항에 트리거어("언제" 등) 부재 grep 확인.
- 게이트(ollama·실DB·Chroma 필요): `eddr golden --golden-set docs/rag_quality/questions.yaml`
  → G08 PASS · 9문항 비회귀. G04("부산 1박2일 언제") 형제 질의도 개선 기대(비회귀만 보장).

## 사전점검 결과 (2026-06-15, self-review)

`questions.yaml` 10문항 전수 확인:
- 트리거어 "언제"는 **G04·G08에만** 존재(둘 다 `answer_type: fact` · `category: simple_fact`).
  photo_list 8문항(G01·02·03·05·06·07·09·10)엔 트리거어 0건 → `order_by_date=False`로 현행
  동등, **회귀 0**.
- 두 fact 문항 모두 trip 시작일을 `date_lane_top`으로 기대(G08 `2019-06-29` · G04 `2018-12-29`,
  within:3). **날짜 오름차순**이 가장 이른 날을 top으로 올려 둘 다 충족 — G08은 FAIL→PASS,
  G04는 PASS 유지(top-3 → top-1).

## 리스크·완화

- 과트리거(photo_list lane이 날짜순으로 뒤집힘) → 정규식을 의문사로 좁게 한정 + 비-fact 골든
  트리거어 부재 사전확인.
- 사진 누락 → semantic 결과·over-fetch 루프 유지, 순서만 변경.
- golden 게이트는 외부 의존(느림) → 단위테스트로 로직 고정 후 게이트는 최종 1회.

## 핵심 파일
- `src/eddr/server/routes/search.py` — `is_date_intent` 신설 · `group_by_kst_date` 인자 · route 배선
- `src/eddr/query/golden.py` — 러너 배선(L250)
- `docs/rag_quality/questions.yaml` — G08 match(참조, 불변)
- `tests/server/test_search.py` — 단위테스트

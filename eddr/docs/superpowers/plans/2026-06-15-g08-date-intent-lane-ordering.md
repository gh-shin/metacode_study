# G08 날짜질의 lane 재정렬 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "이탈리아 언제 갔더라"류 날짜/사실 질의에서 trip 시작일 lane을 상위로 올려 골든 G08을 PASS시킨다(→ 10/10).

**Architecture:** `search.py`에 순수 분류기 `is_date_intent(query)`(시간 의문사 정규식)를 신설하고, `group_by_kst_date`에 `order_by_date` 인자를 추가한다(True=날짜 오름차순, False=현행 rank순). route와 golden 러너 2곳이 `order_by_date=is_date_intent(query)`로 배선한다. `run_search`·추출·프론트 계약은 불변. 사진 집합은 그대로, lane *순서*만 분기.

**Tech Stack:** Python 3.12, stdlib `re`, pytest, FastAPI TestClient. ruff(line-length 100, 편집 시 `ruff check`+`ruff format --check` 게이트 강제).

설계 spec: `docs/superpowers/specs/2026-06-15-g08-date-intent-lane-ordering-design.md`

---

## File Structure

- **Modify** `src/eddr/server/routes/search.py` — `import re` 추가 · `is_date_intent` 신설 · `group_by_kst_date(order_by_date=...)` 인자 · route 응답 조립 배선.
- **Modify** `src/eddr/query/golden.py:250` — 러너 lane 조립을 `order_by_date=is_date_intent(question.question)`로 배선.
- **Test** `tests/server/test_search.py` — `is_date_intent` 단위 + route 날짜순 정렬 통합.
- **Test** `tests/query/test_golden.py` — date-intent 질의 lane 날짜순 정렬.
- **Reference (불변)** `docs/rag_quality/questions.yaml` — G08 match `date_lane_top: {date: "2019-06-29", within: 3}`.

---

## Task 1: `is_date_intent` 분류기

**Files:**
- Modify: `src/eddr/server/routes/search.py` (상단 import + 함수 신설)
- Test: `tests/server/test_search.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/server/test_search.py` 끝에 추가. 상단 import에 `is_date_intent` 추가(`from eddr.server.routes.search import is_date_intent`).

```python
def test_is_date_intent_matches_time_interrogatives():
    assert is_date_intent("내가 이탈리아를 언제 갔더라?")
    assert is_date_intent("부산 여행 몇 년에 갔지?")
    assert is_date_intent("몇월에 찍은 거야")
    assert is_date_intent("며칠에 찍었어")


def test_is_date_intent_ignores_photo_list_queries():
    assert not is_date_intent("이탈리아 여행 사진 찾아줘")
    assert not is_date_intent("바다 풍경 보여줘")
    assert not is_date_intent("용산에서 뭘 먹었었는지 보여줘")
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/shingh/works/eddr && .venv/bin/pytest tests/server/test_search.py -k is_date_intent -q`
Expected: FAIL — `ImportError`/`cannot import name 'is_date_intent'`.

- [ ] **Step 3: 구현** — `src/eddr/server/routes/search.py` 상단 import 블록에 `import re`를 추가(이미 있으면 생략). `group_by_kst_date` 함수 정의 바로 위에 다음을 추가:

```python
_DATE_INTENT_RE = re.compile(r"언제|몇\s*년|몇\s*월|며칠")


def is_date_intent(query: str) -> bool:
    """질의가 명시적 시간(날짜/사실) 의문인지 판정한다 — lane을 날짜순으로 정렬할지 결정.

    "언제"·"몇 년"·"몇 월"·"며칠" 등 시간 의문사만 매칭한다. "여행"·"사진" 같은
    일반어는 비매칭이라 photo_list 질의의 lane 순서(관련도)를 보존한다.

    Args:
        query: 사용자 한국어 질의 원문.

    Returns:
        시간 의문사가 있으면 True.
    """
    return bool(_DATE_INTENT_RE.search(query))
```

- [ ] **Step 4: 통과 확인**

Run: `cd /Users/shingh/works/eddr && .venv/bin/pytest tests/server/test_search.py -k is_date_intent -q`
Expected: PASS (2 passed).

- [ ] **Step 5: 커밋**

```bash
git add src/eddr/server/routes/search.py tests/server/test_search.py
git commit -m "feat: is_date_intent — 시간 의문사 분류기 (G08)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `group_by_kst_date(order_by_date=...)` + route 배선

**Files:**
- Modify: `src/eddr/server/routes/search.py` (`group_by_kst_date` 시그니처·정렬 분기 + route 응답 조립)
- Test: `tests/server/test_search.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/server/test_search.py`에 추가. 기존 `test_search_groups_by_kst_date_and_sorts_by_relevance`와 동일 셋업(`_client`·동일 ordered_ids)이되 질의에 "언제"를 넣어 날짜순을 기대한다.

```python
def test_search_orders_lanes_by_date_for_date_intent_query(tmp_path: Path):
    extractor = FakeExtractor(ExtractedQuery(keywords_en=()))
    client = _client(tmp_path, ["p4", "p6", "p1", "p2", "p7"], extractor)

    body = client.post("/api/search", json={"query": "이 사진들 언제 찍었더라"}).json()

    # "언제" → 날짜 오름차순(rank 무관, 이른 날 top), date 없는 그룹은 말미.
    assert [g["date"] for g in body["groups"]] == ["2018-04-01", "2018-04-02", "2020-01-05", None]
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/shingh/works/eddr && .venv/bin/pytest tests/server/test_search.py -k date_intent_query -q`
Expected: FAIL — 그룹이 여전히 관련도순 `["2020-01-05", "2018-04-01", "2018-04-02", None]`로 나와 assert 불일치.

- [ ] **Step 3: 구현 (a) — `group_by_kst_date` 시그니처·정렬 분기.** `src/eddr/server/routes/search.py`의 `def group_by_kst_date(results: list[PhotoSummary]) -> list[SearchLane]:`를 아래로 교체(시그니처 + 정렬 부분만; `return [...]` 본문은 불변):

```python
def group_by_kst_date(
    results: list[PhotoSummary], order_by_date: bool = False
) -> list[SearchLane]:
    """검색 결과를 KST 달력일 lane으로 묶는다.

    taken_at은 전량 KST aware ISO(D26 M1)라 앞 10자가 KST 달력일이다.
    taken_at 없는 사진은 date=None 그룹으로 모은다. place는 그룹 최빈
    city(없으면 country, 둘 다 없으면 None)다.

    order_by_date=True면(날짜/사실 질의) lane을 날짜 오름차순(가장 이른 날 = trip
    시작일 top, date 없는 그룹은 말미)으로, False면(기본) 그룹 최고 관련도순으로 정렬한다.
    그룹 *내부* 사진 순서(rank 오름차순)는 두 경우 모두 유지한다.
    """
    by_date: dict[str | None, list[PhotoSummary]] = {}
    for photo in results:
        date = photo.taken_at[:10] if photo.taken_at else None
        by_date.setdefault(date, []).append(photo)
    if order_by_date:
        # 날짜/사실 질의 — 가장 이른 날(trip 시작일)을 top으로, date 없는 그룹은 말미.
        ordered = sorted(by_date.items(), key=lambda item: (item[0] is None, item[0] or ""))
    else:
        # semantic 결과는 rank 오름차순이라 그룹 내 첫 사진의 rank가 그룹 최고 관련도다.
        ordered = sorted(by_date.items(), key=lambda item: item[1][0].rank)
    return [
```

(주의: `ordered = sorted(...)` 한 줄을 if/else 분기로 교체하는 것이며, 그 아래 `return [ SearchLane(...) ... ]` 본문은 손대지 않는다.)

- [ ] **Step 4: 구현 (b) — route 배선.** 같은 파일 `search` 핸들러의 응답 조립(`return {... "groups": [asdict(lane) for lane in group_by_kst_date(results)], ...}`)을 `lanes` 변수 추출로 교체:

```python
    lanes = group_by_kst_date(results, order_by_date=is_date_intent(query))
    return {
        "interpretation": asdict(extracted),
        # SearchLane → dict 직렬화는 라우트 가장자리에서만 — 내부 소비처(골든 러너)는
        # 객체 그대로 받는다. asdict가 중첩 dataclass·tuple을 재귀 변환한다.
        "groups": [asdict(lane) for lane in lanes],
        "total": len(results),
    }
```

- [ ] **Step 5: 통과 확인 (신규 + 기존 관련도 테스트 회귀 없음)**

Run: `cd /Users/shingh/works/eddr && .venv/bin/pytest tests/server/test_search.py -q`
Expected: PASS (전부 — 신규 date_intent 테스트 + 기존 `sorts_by_relevance`가 `order_by_date=False` 기본으로 동등 유지).

- [ ] **Step 6: 커밋**

```bash
git add src/eddr/server/routes/search.py tests/server/test_search.py
git commit -m "feat: group_by_kst_date order_by_date 인자 + route 배선 (G08)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: golden 러너 배선

**Files:**
- Modify: `src/eddr/query/golden.py` (러너 lane 조립 + import)
- Test: `tests/query/test_golden.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/query/test_golden.py`에 추가. 이른 날짜(2023-05-05)에 더 나쁜 rank를 줘서, rank순이면 상위 1 밖·날짜순이면 top이 되게 한다(와이어링 없으면 FAIL).

```python
def test_run_golden_set_orders_lanes_by_date_for_fact_question():
    """date-intent 질의는 lane을 날짜순 정렬 — trip 시작일이 상위에 온다 (G08)."""
    results = [
        _photo("p1", "2024-01-10 10:00:00+09:00", 1),  # 늦은 날짜, 좋은 rank
        _photo("p2", "2023-05-05 10:00:00+09:00", 2),  # 이른 날짜, 나쁜 rank
    ]

    def search_fn(query: str):
        return ExtractedQuery(keywords_en=()), list(results)

    question = GoldenQuestion(
        id="T_DATE",
        question="이 사진들 언제 찍었더라?",  # "언제" → date intent
        match={"date_lane_top": {"date": "2023-05-05", "within": 1}},
    )

    rows = run_golden_set([question], search_fn)

    assert rows[0].verdict == "PASS"
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/shingh/works/eddr && .venv/bin/pytest tests/query/test_golden.py -k orders_lanes_by_date -q`
Expected: FAIL — 와이어링 전이라 lane이 rank순(2024-01-10 top) → `date_lane_top {2023-05-05, within:1}` 미충족 → verdict "FAIL".

- [ ] **Step 3: 구현** — `src/eddr/query/golden.py`에서 (a) import 확장, (b) lane 조립 배선.

(a) 러너 함수 안 `from eddr.server.routes.search import group_by_kst_date`(약 L240)를 교체:

```python
    from eddr.server.routes.search import group_by_kst_date, is_date_intent
```

(b) `groups = group_by_kst_date(results)`(약 L250)를 교체:

```python
            groups = group_by_kst_date(
                results, order_by_date=is_date_intent(question.question)
            )
```

- [ ] **Step 4: 통과 확인 (신규 + 기존 golden 테스트 회귀 없음)**

Run: `cd /Users/shingh/works/eddr && .venv/bin/pytest tests/query/test_golden.py -q`
Expected: PASS (전부 — 기존 T02 "언제"+date_lane_top는 이른 날짜가 이미 top-rank라 날짜순으로도 PASS 유지).

- [ ] **Step 5: 커밋**

```bash
git add src/eddr/query/golden.py tests/query/test_golden.py
git commit -m "feat: golden 러너 date-intent lane 날짜순 배선 (G08)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: 회귀 사전점검 + 골든 게이트

**Files:** 없음(검증 전용). `docs/rag_quality/questions.yaml`(참조).

- [ ] **Step 1: 트리거어 사전점검** — 비-fact 골든 문항이 트리거어를 안 가져야 회귀 0.

Run: `cd /Users/shingh/works/eddr && grep -nE "언제|몇 *년|몇 *월|며칠" docs/rag_quality/questions.yaml`
Expected: 매칭은 G04(L98)·G08(L180)의 `question:` 줄에만(둘 다 `answer_type: fact`). 그 외 문항 0건. (다른 문항이 나오면 정규식을 더 좁히고 Task 1로 복귀.)

- [ ] **Step 2: 전체 단위 스위트 green**

Run: `cd /Users/shingh/works/eddr && .venv/bin/pytest -q`
Expected: 전량 PASS (기존 329 + 신규 4 테스트). `uvx ruff check src tests` clean.

- [ ] **Step 3: 골든 게이트 (ollama·실DB·Chroma 필요)** — 실제 추출·검색으로 G08 통과·9문항 비회귀 확인.

Run: `cd /Users/shingh/works/eddr && .venv/bin/eddr golden --golden-set docs/rag_quality/questions.yaml --db data/eddr.sqlite`
Expected: 리포트에 **G08 PASS**, 그리고 G01~G07·G09·G10 비회귀(이전 9 PASS 유지) → **10/10**. G04도 PASS 유지(날짜순으로 trip 시작일 top-1). ollama 미기동이면 503/ConnectionError — ollama 기동 후 재실행.

- [ ] **Step 4: 결과 기록·커밋(해당 시)** — 골든 리포트 산출물(`reports/golden/` 등) 및 TODO 🔎 G08 항목 완료 처리. 리포트 경로는 러너 출력 참조.

```bash
git add -A
git commit -m "test: G08 골든 게이트 통과 — 10/10 (날짜질의 lane 재정렬)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- is_date_intent 분류기 → Task 1 ✓
- group_by_kst_date order_by_date(날짜 오름차순·None 말미) → Task 2 ✓
- route 배선 → Task 2 ✓ · golden 러너 배선 → Task 3 ✓
- run_search 불변 → 모든 task가 시그니처 미변경 ✓
- 회귀 사전점검 + 골든 게이트 → Task 4 ✓
- 단위테스트(분류기·정렬·회귀 가드) → Task 1·2·3 ✓

**Placeholder scan:** 모든 코드 블록은 실제 코드(정규식·sorted 키·테스트 PhotoSummary는 기존 `_photo` 빌더 사용). placeholder 없음.

**Type consistency:** `is_date_intent(query: str) -> bool` · `group_by_kst_date(results, order_by_date: bool = False)` · `_photo(photo_id, taken_at, rank, ...)`(test_golden.py 기존) · `GoldenQuestion(id, question, match)`(기존) — task 간 일치.

**주의:** Task 2 Step 3은 `ordered = sorted(...)` 한 줄만 if/else로 교체하고 `return [...]` 본문은 보존. Task 2 Step 4는 route 응답을 `lanes` 변수로 추출(긴 줄 ruff format 회피).

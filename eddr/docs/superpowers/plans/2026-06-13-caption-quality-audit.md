# Caption Quality Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a non-mutating caption/search audit path that separates caption mislabeling from retrieval amplification for food and other visually ambiguous searches.

**Architecture:** Add a small query-audit module that reuses the existing DB, vector store, embedding client, FTS5 lexical leg, and RRF semantics without changing production search ranking. Add an experimental food-guard prompt variant that preserves the existing `Search keywords:` contract so prompt/model tests can compare outputs safely.

**Tech Stack:** Python, SQLite FTS5, existing `QueryService` ranking primitives, Ollama prompt names, pytest.

---

### Task 1: Caption Search Audit Trace

**Files:**
- Create: `src/eddr/query/audit.py`
- Create: `tests/query/test_caption_audit.py`
- Modify: `src/eddr/db/repository.py`

- [ ] **Step 1: Write the failing test**

```python
def test_trace_caption_search_separates_caption_error_from_retrieval_noise(tmp_path):
    db = make_audit_db(tmp_path)
    store = FakeVectorStore(["wrong-noodle", "real-naengmyeon", "sprouts"])
    labels = {
        "wrong-noodle": CaptionAuditLabel(visual_target=False, caption_claims_target=True),
        "real-naengmyeon": CaptionAuditLabel(visual_target=True, caption_claims_target=True),
    }

    report = trace_caption_search(
        db=db,
        vector_store=store,
        embedding_client=FakeEmbeddingClient(),
        query="냉면",
        keywords=["cold noodles", "food"],
        k=3,
        labels=labels,
    )

    wrong = next(hit for hit in report.hits if hit.photo_id == "wrong-noodle")
    assert wrong.vector_rank == 1
    assert wrong.lexical_rank is not None
    assert wrong.bucket == "caption_false_positive"
    assert report.keyword_stats["food"].document_count == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/query/test_caption_audit.py -q`

Expected: FAIL because `eddr.query.audit` and `count_caption_matches` do not exist.

- [ ] **Step 3: Write minimal implementation**

Create immutable dataclasses for labels, keyword stats, hit provenance, and query reports. Implement `trace_caption_search()` with the same query embedding instruction, vector over-fetch, FTS5 lexical match, duplicate filtering, and RRF score components used by `QueryService`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/query/test_caption_audit.py -q`

Expected: PASS.

### Task 2: Experimental Food Guard Prompt

**Files:**
- Modify: `src/eddr/vision/prompt.py`
- Modify: `tests/vision/test_prompt.py`

- [ ] **Step 1: Write the failing test**

```python
def test_food_guard_prompt_preserves_keyword_contract_and_rejects_unsupported_noodles():
    prompt = build_prompt_for_photo(photo, "p3_hybrid_food_guard")

    assert "Search keywords:" in prompt
    assert "Use \"noodles\" only when actual noodle strands are visible" in prompt
    assert "bean sprouts" in prompt
    assert "Do not invent exact dish names" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/vision/test_prompt.py -q`

Expected: FAIL because the prompt name is unknown.

- [ ] **Step 3: Write minimal implementation**

Add `P3_HYBRID_FOOD_GUARD_PROMPT_NAME` and route it to the v2 metadata prompt plus food-specific rules. Do not make it the default prompt.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/vision/test_prompt.py -q`

Expected: PASS.

### Task 3: CLI Hook For Audit Reports

**Files:**
- Modify: `src/eddr/cli.py`
- Create: `tests/cli/test_caption_audit_cli.py`

- [ ] **Step 1: Write the failing test**

```python
def test_cli_search_audit_writes_json_report(tmp_path, monkeypatch):
    rc = main([
        "search", "audit", "냉면",
        "--db", str(db_path),
        "--chroma", str(tmp_path / "chroma"),
        "--keyword", "cold noodles",
        "--keyword", "food",
        "--out", str(tmp_path / "audit.json"),
    ])

    assert rc == 0
    assert json.loads((tmp_path / "audit.json").read_text())["query"] == "냉면"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_caption_audit_cli.py -q`

Expected: FAIL because `search audit` is not registered.

- [ ] **Step 3: Write minimal implementation**

Add `eddr search audit` with repeated `--keyword`, `--k`, and `--out`. The command writes JSON and does not mutate SQLite or Chroma.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/cli/test_caption_audit_cli.py -q`

Expected: PASS.

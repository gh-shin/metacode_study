# AGENTS.md - src/eddr/eval

## Purpose

검색/RAG 품질 실험 산출물을 읽어 과제용 한국어 보고서와 비교 요약을 만든다. runtime 검색 경로가 아니라 report rendering 계층이다.

## Read First

- `rag_quality.py`: question spec, experiment JSONL, golden report parsing, markdown rendering.
- 관련 테스트: `tests/eval/`.

## Public Surface

| Symbol | Input | Output | Notes |
|---|---|---|---|
| `load_question_specs(path)` | YAML/JSON-like question spec path | `list[QuestionSpec]` | assignment question metadata. |
| `load_experiment_records(path)` | experiments JSONL | `list[ExperimentRecord]` | append-order experiment rows. |
| `summarize_experiments(records, baseline_label)` | records and baseline | rows `list[dict]` | deltas against baseline. |
| `render_assignment_report()` | project artifact paths | markdown `str` | Korean report. |

## Inputs

- question specs.
- retrieval benchmark JSONL.
- golden report markdown.

## Outputs

- in-memory markdown report string.
- summary rows with recall/latency deltas.

## Side Effects

- Public functions here mostly read files and return strings/rows.
- Writing report files is normally done by caller/script.

## Exceptions / Failure Modes

- missing artifacts, malformed JSONL, missing baseline label.
- golden report parser may return `None` if report shape is absent.

## Invariants

- Evaluation reporting must not mutate DB/vector state.
- Metrics reported as “passed” must come from current artifacts, not assumptions.

## Tests

- `pytest tests/eval`

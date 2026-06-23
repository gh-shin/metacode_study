# AGENTS.md - src/eddr/query

## Purpose

한국어 자연어 질의를 구조화하고, caption/vector/note/trip/date 조건을 결합해 내부 검색 결과를 만든다. D26 이후 외부 LLM tool surface가 아니라 서버가 호출하는 로컬 검색 서비스다.

## Read First

- `tools.py`: `QueryService`, response dataclass, RRF fusion.
- `extract.py`: Ollama 기반 query extraction.
- `golden.py`: golden set runner and match evaluator.
- `captions.py`: caption body/keyword parser.
- `notes_bm25.py`: notes lexical index.
- `audit.py`: caption search provenance audit.
- `retrieval_config.py`, `rerankers.py`, `expansion.py`: 실험 옵션.
- 호출자: `server/routes/search.py`, `cli.py`.
- 관련 테스트: `tests/query/`, `tests/cli/test_golden_cli.py`, `tests/cli/test_caption_audit_cli.py`.

## Public Surface

| Symbol | Input | Output | Notes |
|---|---|---|---|
| `QueryService.search_photos` | date/place/caption/trip filters, limit | `list[PhotoSummary]` | DB lexical/filter search. |
| `QueryService.semantic_search_photos` | query, k, filters, keywords | `list[PhotoSummary]` | vector + lexical/note fusion. |
| `QueryService.list_trips` | countries/date/limit | `list[TripSummary]` | trip lookup. |
| `QueryService.get_trip` | trip_id | `TripDetail | None` | trip detail with sample photos. |
| `QueryService.get_photo` | photo_id | `PhotoDetail | None` | single photo detail. |
| `QueryExtractor.extract` | Korean query | `ExtractedQuery` | keywords/date/place extraction. |
| `run_golden_set` | questions, search_fn | `list[GoldenRow]` | regression runner. |
| `evaluate_match` | match rules, results, lanes | pass/fail and reasons | deterministic golden scoring. |

## Inputs

- Korean user query.
- SQLite DB and vector store.
- query embedding client.
- optional note vector/BM25 stores.
- golden YAML.

## Outputs

- `PhotoSummary`, `TripSummary`, `TripDetail`, `PhotoDetail`.
- `ExtractedQuery`.
- golden markdown reports.
- audit JSON/report data.

## Side Effects

- Normal query methods should not mutate DB.
- golden/report writer writes markdown files.
- audit CLI writes report JSON.
- query extraction calls local Ollama.

## Exceptions / Failure Modes

- extractor parse failure sets fallback behavior.
- vector store or embedding model unavailable can break semantic search.
- optional reranker/expander dependencies may be absent; build functions can return `None`.

## Invariants

- limit must be clamped before exposing large result sets.
- precise coordinates are allowed only inside local server/browser boundary.
- Korean query embedding uses original query; extracted English keywords help lexical/BM25 legs.

## Tests

- `pytest tests/query`
- `pytest tests/cli/test_golden_cli.py tests/cli/test_caption_audit_cli.py`

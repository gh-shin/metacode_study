# AGENTS.md - src/eddr/search

## Purpose

초기/단순 semantic search helper 계층이다. query text를 embedding하고 vector store hit를 DB photo/caption metadata와 결합해 `SemanticSearchResult`를 반환한다.

## Read First

- `semantic.py`: protocol, result dataclass, `semantic_search`.
- 호출 CLI: `eddr search semantic`.
- 관련 테스트: `tests/search/test_semantic.py`.

## Public Surface

| Symbol | Input | Output | Notes |
|---|---|---|---|
| `semantic_search(query, db, vector_store, embedding_client, k, where)` | query text, stores, k/filter | `list[SemanticSearchResult]` | query embedding → vector hit → DB join. |
| `SemanticSearchResult` | photo metadata + distance | dataclass | CLI display/result object. |
| `QueryEmbeddingClient` | texts | embeddings | protocol. |
| `VectorSearchStore` | embedding, k, where | vector hits | protocol. |

## Inputs

- natural language query.
- vector store.
- embedding client.
- optional metadata filter.

## Outputs

- `SemanticSearchResult(photo_id, source, source_uri, image_path, taken_at, caption, distance)`.

## Side Effects

- Embedding client call.
- DB/vector reads only.

## Exceptions / Failure Modes

- embedding client unavailable.
- vector hit points to missing DB photo.
- missing caption returns `caption=None`.

## Invariants

- This package is smaller than `query`; new full search behavior usually belongs in `src/eddr/query`.

## Tests

- `pytest tests/search/test_semantic.py`

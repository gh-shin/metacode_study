# AGENTS.md - src/eddr/vector

## Purpose

Embedding vector 저장소 adapter 계층이다. 운영은 Chroma persistent store를 쓰고, 테스트/가벼운 실행은 in-memory store를 쓴다.

## Read First

- `chroma_store.py`: ChromaDB `PersistentClient` adapter.
- `memory_store.py`: dict 기반 테스트 store.
- 관련 호출자: `vision`, `query`, `search`, `server.deps`.
- 관련 테스트: `tests/vector/test_chroma_store.py`.

## Public Surface

| Symbol | Input | Output | Notes |
|---|---|---|---|
| `VectorHit` | id/photo_id/document/metadata/distance | dataclass | query result. |
| `ChromaVectorStore.upsert` | ids, embeddings, documents, metadatas | `None` | persistent upsert. |
| `ChromaVectorStore.query` | embedding, k, where | `list[VectorHit]` | nearest vector search. |
| `ChromaVectorStore.delete` | ids | `None` | note/caption vector deletion. |
| `ChromaVectorStore.count` | none | `int` | collection size. |
| `MemoryVectorStore` | same upsert/query/count | same | tests and protocol compatibility. |

## Inputs

- `Embedding`: `list[float]`.
- vector id list.
- document text.
- metadata dict, usually including `photo_id`.
- optional Chroma where filter.

## Outputs

- `VectorHit(id, photo_id, document, metadata, distance)`.

## Side Effects

- Chroma persistent directory를 읽고 쓴다.
- memory store는 process-local dict만 수정한다.

## Exceptions / Failure Modes

- Chroma path/collection 초기화 실패.
- embedding dimension mismatch.
- where filter가 metadata shape와 맞지 않으면 query 결과가 비거나 Chroma 오류가 날 수 있다.

## Invariants

- `photo_id` metadata는 query result를 DB photo row와 다시 결합하는 key다.
- vector id와 SQLite embeddings record는 호출자가 동기화해야 한다.

## Tests

- `pytest tests/vector/test_chroma_store.py`

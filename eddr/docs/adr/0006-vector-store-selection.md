# ADR-0006: Vector Store Selection — Chroma sidecar over FAISS/sqlite-vec

## Status

Accepted (2026-06-07)

## Context

EDDR의 기존 계획은 단일 SQLite 파일에 `sqlite-vec`를 붙여 메타데이터와 벡터를 함께 보관하는 방식이었다. 2026-06-10까지의 구축 목표가 **모든 소스의 기초 DB 적재 + full Vision caption/embedding 적재**로 확장되면서, 이번 단계의 핵심 위험은 raw vector search 속도가 아니라 다음 세 가지가 되었다.

- Photos/iCloud export가 오래 걸리거나 실패할 수 있음
- caption/embedding 생성이 long-running batch라 중단 후 resume이 필수
- 검색 결과는 벡터 hit 이후 SQLite의 canonical photo metadata와 다시 join되어야 함

검토 대상:

- **Chroma**: persistent local vector DB. upsert, metadata filter, collection count/query가 built-in.
- **FAISS**: 고성능 vector index library. 빠르지만 docstore, metadata filter, persistence mapping, resume-safe upsert를 별도 구현해야 함.
- **sqlite-vec**: 단일 SQLite 장점이 있으나 현재 프로젝트에 dependency/schema가 없고, 6/10까지 Chroma/FAISS 평가와 full Vision 적재를 병행하기엔 도입 검증이 부족함.

## Decision

이번 구축 단계의 벡터 저장소는 **Chroma persistent sidecar**로 채택한다.

- SQLite(`data/eddr.sqlite`)는 canonical ledger: `photos`, `captions`, `embeddings`, `index_errors`, status checkpoint를 소유한다.
- Chroma(`data/index/chroma`)는 `eddr_caption_text_v1` collection으로 caption-text embedding 검색을 소유한다.
- SQLite `embeddings.vector_id`는 Chroma id를 보존한다. 벡터 payload 자체는 SQLite에 저장하지 않는다.
- FAISS는 이번 단계에서 제외하고, 검색 속도가 실제 병목으로 확인될 때만 재평가한다.

## Consequences

**Positive:**

- full Vision batch 중단/재실행 시 `photos.indexing_status`와 Chroma upsert를 함께 사용해 resume이 단순하다.
- metadata filter(`source`, `kind`, `model_id`)가 vector store API에 있다.
- LangChain 예제 코드의 `persist_directory`, `add_texts`/`upsert`, `similarity_search`, `as_retriever` 패턴과 목적이 맞다.

**Negative:**

- 단일 SQLite 파일 백업이라는 기존 단순성은 일부 약화된다. 백업 단위는 `data/eddr.sqlite` + `data/index/chroma/`가 된다.
- Chroma dependency surface가 크다. Sonatype MCP 확인은 현재 인증 토큰 부재로 수행하지 못했으므로, lockfile pinning과 테스트로 관리한다.
- FAISS 대비 raw ANN 튜닝 여지는 작다. 현재 EDDR 규모에서는 수용한다.

## Implementation Notes

- CLI:
  - `eddr db init`
  - `eddr db load-sources`
  - `eddr photos export`
  - `eddr vision run`
  - `eddr search semantic`
- Bulk caption model: `gemma4:e2b` + P3_hybrid prompt.
- Caption-text embedding model: `qwen3-embedding:8b`.
- `qwen3-vl:8b`는 smoke에서 warm 21-24s/image로 측정되어 bulk caption 기본값에서 제외한다.

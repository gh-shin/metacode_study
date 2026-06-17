---
title: "Vector store 선택"
source: ["docs/adr/0006-vector-store-selection.md", "docs/PLAN.md#7"]
last_verified: 2026-06-07
status: fresh
confidence: high
tags: [vector, chroma, faiss, sqlite]
---

# Vector store 선택

2026-06-10 구축 단계의 벡터 저장소는 **Chroma persistent sidecar**로 채택한다.

## 결정

- SQLite(`data/eddr.sqlite`)는 canonical ledger: `photos`, `captions`, `embeddings`, `index_errors`, status checkpoint를 보관한다.
- Chroma(`data/index/chroma`)는 `eddr_caption_text_v1` collection으로 caption-text embedding 검색을 담당한다.
- SQLite `embeddings.vector_id`가 Chroma id를 참조한다. 벡터 payload는 SQLite에 저장하지 않는다.
- FAISS는 이번 단계에서 제외한다.

## 이유

이번 병목은 raw ANN 성능이 아니라 source materialization과 long-running Vision resume이다. Chroma는 persistence, upsert, metadata filter, count/query가 built-in이라 6/10까지의 데이터 적재 리스크가 FAISS보다 낮다.

## 운영 기본값

- bulk caption: `gemma4:e2b` + P3_hybrid
- caption_text embedding: `qwen3-embedding:8b`
- distance metric: Chroma 기본 **L2(squared)** — 별도 지정 없음. `qwen3-embedding` 정규화 벡터라 cosine과 검색 순위 동일. 절대 거리 임계값을 쓸 땐 L2 스케일 주의.
- `qwen3-vl:8b`는 품질 후보로 유지하되 bulk caption 기본값은 아님

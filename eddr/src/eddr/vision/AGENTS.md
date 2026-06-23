# AGENTS.md - src/eddr/vision

## Purpose

사진 caption 생성, caption text embedding, prompt A/B, 민감 메타데이터 누출 검사를 담당한다. 로컬 또는 LAN Ollama 서버를 호출하고 결과를 SQLite/Chroma에 저장한다.

## Read First

- `batch.py`: caption batch 실행과 DB/vector persistence.
- `ollama_client.py`: Ollama image caption/embed client.
- `prompt.py`: caption prompt와 privacy guard.
- `prompt_ab.py`, `prompt_ab_eval.py`: prompt 실험과 평가.
- 호출 CLI: `eddr vision run`, `recaption`, `reindex-vectors`, `prompt-ab`, `prompt-ab-eval`.
- 관련 테스트: `tests/vision/`.

## Public Surface

| Symbol | Input | Output | Notes |
|---|---|---|---|
| `run_caption_text_batch` | DB, vector store, vision client, limit | `VisionBatchReport` | 단일 client 순차 caption+embedding. |
| `run_caption_text_batch_dual` | local/remote caption client, embed client | `VisionBatchReport` | caption 분산, embedding 저장은 단일 경로. |
| `run_caption_text_batch_routed_dual` | DB, vector store, embed client | `VisionBatchReport` | doc/nondoc 라우팅 재캡션. |
| `OllamaVisionClient` | Ollama host/model 설정 | captions, embeddings | HTTP client wrapper. |
| `build_prompt_for_photo` | `PhotoRecord`, prompt name | prompt `str` | prompt variant 선택. |
| `ensure_caption_has_no_sensitive_metadata` | caption text, photo | `None` or `ValueError` | 좌표/파일경로 등 누출 방지. |
| `run_prompt_ab` | DB, client, prompt names/photo ids | `PromptAbReport` | JSONL 실험 결과 생성. |
| `evaluate_prompt_ab_outputs` | JSONL + labels | `PromptAbEvaluationReport` | gate summary. |

## Inputs

- `PhotoRecord` with `image_path` and metadata hints.
- Ollama caption model and embedding model.
- Chroma vector store collection.
- prompt names.
- optional remote Ollama host.

## Outputs

- captions table row.
- caption text vector in Chroma.
- embeddings table record.
- prompt A/B JSONL and evaluation report.

## Side Effects

- 로컬/원격 Ollama HTTP 호출.
- 이미지 변환용 임시 파일 생성 가능.
- SQLite captions/embeddings/index status 업데이트.
- Chroma upsert/delete/query.

## Exceptions / Failure Modes

- 이미지 파일 없음, HEIC/TIFF 변환 실패, Ollama timeout/model 없음.
- caption에 민감 메타데이터가 포함되면 `ValueError`.
- batch 실패는 가능한 경우 `VisionBatchReport.failed`와 DB error record로 남긴다.

## Invariants

- 이미지 바이너리는 외부 LLM으로 보내지 않는다. Ollama는 로컬 또는 사설 LAN 노드만 전제한다.
- caption text embedding vector id와 DB embedding record는 동기화되어야 한다.
- prompt 문자열 변경은 검색 품질과 privacy guard에 직접 영향을 준다.

## Tests

- `pytest tests/vision`

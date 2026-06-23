# src/eddr/server

FastAPI 앱, 전역 상태 조립, SPA 정적 서빙을 담당한다. D26 이후 사용자-facing 경로는
채팅이 아니라 지도, 검색, 사진 상세, 수동 지오코딩 API다.

## 어디에 끼는가

```mermaid
flowchart TD
  CLI[eddr serve-api] --> CFG[ServerConfig]
  CFG --> STATE[build_state -> AppState]
  STATE --> DB[EddrDatabase]
  STATE --> CAP[Chroma eddr_caption_text_v1]
  STATE --> NOTE[Chroma eddr_note_text_v1]
  STATE --> EMB[OllamaVisionClient qwen3-embedding:8b]
  STATE --> EXT[QueryExtractor gemma4:e2b]
  STATE --> BM25[NotesBM25Index]
  STATE --> RET[RetrievalConfig expander/reranker]
  STATE --> GEO[NominatimClient]
  STATE --> APP[create_app]
  APP --> ROUTES[/api routes]
  APP --> SPA[web/dist if exists]
```

## AppState 구성

| 속성 | 역할 |
|---|---|
| `config` | `EDDR_ROOT`, SQLite, Chroma, Ollama host, retrieval variant |
| `service` | `QueryService`. 검색, 사진 상세, trip 조회의 중심 |
| `extractor` | `QueryExtractor(gemma4:e2b)`. `/api/search` 해석 |
| `geocoder` | Nominatim forward/reverse client |
| `note_store` | Chroma `eddr_note_text_v1` collection |
| `retrieval_config` | reranker, query expansion 등 실험 variant |
| `thumb_dir` | `EDDR_ROOT/data/cache/thumbs` |

## 런타임 계약

| 항목 | 계약 |
|---|---|
| root | 모든 상대 이미지 경로와 기본 데이터 경로는 `EDDR_ROOT` 기준 |
| SQLite | `data/eddr.sqlite` 기본 |
| Chroma | `data/index/chroma` 기본 |
| SPA | `web/dist`가 있으면 `/`에 정적 마운트. 없으면 API만 |
| LAN bind | loopback 외 host는 무인증 API 노출 경고를 출력 |
| chat route | 의도적으로 없음. `/api/chat`은 D26에서 제거된 surface |

## 요청 처리 경계

블로킹 Ollama 호출이 있는 검색과 note 임베딩은 FastAPI sync/threadpool 경로를 탄다.
검색 라우트 자체는 읽기 전용이고 별도 chat lock이 없다. Ollama 동시성은 Ollama 쪽 큐에 맡긴다.

## 검증 방법

- AppState/app factory: `uv run pytest tests/server/test_deps.py tests/server/test_api.py`
- route 전체: `uv run pytest tests/server`

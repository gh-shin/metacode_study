# AGENTS.md - src/eddr/server

## Purpose

FastAPI 서버 조립 계층이다. `EDDR_ROOT` 기준으로 DB/Chroma/image path를 해석하고, query/geocode/photo/map/status routes에 `AppState`를 주입한다.

## Read First

- `deps.py`: `ServerConfig`, `AppState`, state builder, image path resolver.
- `app.py`: FastAPI app/router assembly and uvicorn serving.
- `thumbnails.py`: local thumbnail cache generation.
- `routes/`: HTTP endpoints.
- 호출 CLI: `eddr serve-api`.
- 관련 테스트: `tests/server/`.

## Public Surface

| Symbol | Input | Output | Notes |
|---|---|---|---|
| `ServerConfig` | root/db/chroma/ollama/retrieval config | config object | path contract. |
| `AppState` | DB/query/geocode/vector/extractor objects | state object | process global dependency. |
| `resolve_image_path(root, image_path)` | root, DB image path | absolute `Path` | relative path anchored at root. |
| `build_state(config)` | `ServerConfig` | `AppState` | production dependency wiring. |
| `create_app(state)` | `AppState` | `FastAPI` | testable app assembly. |
| `serve_api(config, host, port)` | config/listen address | blocking server | uvicorn entry. |
| `get_thumbnail(source_path, cache_dir, photo_id, size)` | source path/cache/id/size | `Path | None` | JPEG thumbnail cache. |

## Inputs

- `EDDR_ROOT` or `--root`.
- SQLite path.
- Chroma path.
- optional Ollama host.
- HTTP requests from local web SPA.

## Outputs

- FastAPI app.
- JSON API responses from routes.
- thumbnail JPEG files under cache.

## Side Effects

- Opens SQLite and Chroma.
- Calls Ollama via query extractor/embedding clients.
- Reads original image files.
- Writes thumbnail cache.

## Exceptions / Failure Modes

- Missing DB/Chroma/image path.
- image path escaping root must be rejected by resolver.
- thumbnail conversion can fail and return 404/None path through route.

## Invariants

- Server is local personal app surface, not multi-user auth boundary.
- `EDDR_ROOT` is the base for relative image paths and default data paths.
- Routes should receive dependencies through `AppState`, not rebuild clients per request.

## Tests

- `pytest tests/server`

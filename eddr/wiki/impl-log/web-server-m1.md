---
title: "D25 M1 — FastAPI API 서버 (eddr serve-api)"
source: ["docs/prd.md", "docs/adr/0008-web-server-contracts.md", "docs/scenario.md"]
last_verified: 2026-06-11
status: fresh
confidence: high
tags: [web, server, fastapi, impl, m1]
---

# D25 M1 — FastAPI API 서버 구현 (2026-06-11)

ADR-0008(`f605b86`) → 구현(`f00539d`, 15 files +646). 테스트 suite 165 → **201 passed**.
아키텍처 요약은 [[web-app]](../architecture/web-app.md), 3계약은 [[web-server-contracts]](../decisions/web-server-contracts.md).

## 구현 내역

- **`eddr serve-api`** (cli.py): 기본 `127.0.0.1:8000`. `EDDR_ROOT` = `--root` > env > CWD,
  db·chroma·썸네일 캐시 기본 경로를 root에서 파생 → 임의 디렉터리 기동.
  `--backend ollama`로 API 키 없이 전체 경로 검증 가능(serve와 동일 옵션).
- **`server/deps.py`**: `ServerConfig`(frozen dataclass) + `AppState` 전역 1개(서비스·엔진·
  `asyncio.Lock`) + `resolve_image_path`(절대경로 그대로, 상대는 root 기준) + `build_state`
  (Gradio `serve()`와 동형 조립). pydantic 미도입 유지 — 요청 본문은 `Body()` dict 수동 검증.
- **`server/routes/`**: chat(빈 message 422·**busy 409**(락 선검사, 큐잉 금지 — 단일 세션에
  발화 섞임 방지)·엔진 예외 502 원인 전달·`run_in_threadpool`), photos(상세 = `get_photo`
  dataclass asdict 그대로 — 좌표·경로 필드 자체 부재, thumb은 sync 라우트 = FastAPI 자동
  threadpool), status(`indexing_stats` + 신규 `indexing_stage_counts`(원시 분포) +
  path_health 표본 20).
- **`server/thumbnails.py`**: `{photo_id}_{size}.jpg`(`:` → `_` 치환), size {320,1280}
  화이트리스트, 전 포맷 JPEG(q85), `ImageOps.exif_transpose`(모바일 회전 보존),
  single-flight(키별 threading.Lock) + tmp→rename(중단 시 손상 캐시 방지).
- deps: fastapi·uvicorn(본)·httpx(dev). `uv lock` + `uv pip install`로 추가 — `uv sync`
  회피(eda ad-hoc 패키지 보존).

## 수용 결과 — PASS 7/7 (sonnet 판정, /tmp/eddr_m1_accept/)

| 항목 | 결과 |
|---|---|
| 임의 디렉터리 기동 | `cd /tmp` + `EDDR_ROOT=…` → healthz **1초** 만에 up |
| path_health | **20/20 healthy** — EDDR_ROOT 계약 증명 (M1 게이트) |
| status | ready=total=**9,218** · stages 합 11,689(caption_done 5,623·trip_assigned 3,760·skipped_video 2,306) |
| thumb (실 HEIC) | 200 image/jpeg **320×320 37.8KB** · 캐시 히트 **2.5ms**(NFR p95<200ms) · size 999 → 422 |
| detail privacy | latitude/longitude/image_path 키 부재 (ADR-0001 웹 확장) |
| **curl G08** | "2019-06-29~07-12 이탈리아 · 278장" — 정답, ollama qwen3.6:27b **2m18s** |

## 관찰 (회귀 아님)

1. **G08 응답 photo_ids 빈 배열** — `list_trips`는 설계상 사진 id를 반환하지 않음(엔진
   `_execute_tool` ids `[]`) — Gradio 경로와 동일 동작. R1(사실형) 답변엔 그리드가 없어도
   무방하나, M2 UI에서 fact 답변에 대표 사진을 원하면 `get_trip`(sample_photos 5장) 유도를
   프롬프트에서 검토.
2. **ollama 답변 자기모순** — "2박 3일 (약 12일)" 표현. 백엔드(qwen3.6:27b) 품질 문제로
   본선 Claude와 무관 — ⑧ 2차(실 API)에서 비교 기준.
3. starlette TestClient deprecation warning 1건(httpx 관련) — 동작 영향 없음, starlette
   업그레이드 시 재확인.

## 다음 (M2)

`web/`(Vite+React+TS) 채팅+그리드+라이트박스 반응형 → 폰 브라우저 골든셋 9/10 동등 →
`query/app.py`(Gradio) 삭제 + pyproject `gradio` 제거 (prd 확정 ⑤). `/api/chat/history`·
`/api/photos/{id}/original`도 M2 표면.

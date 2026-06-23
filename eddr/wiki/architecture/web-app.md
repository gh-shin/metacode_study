---
title: "웹 앱 아키텍처 (D26 전환 중) — FastAPI + React 지도 검색 SPA"
source: ["docs/prd.md", "docs/adr/0009-map-local-search.md", "docs/adr/0008-web-server-contracts.md", "docs/scenario.md"]
last_verified: 2026-06-21
status: fresh
confidence: high
tags: [web, server, fastapi, react, maplibre, architecture]
---

# 웹 앱 아키텍처 (D26 전환 중)

설계 권위는 [docs/prd.md](../../docs/prd.md)(v2) — **지도 중심 로컬 검색 앱**([[local-search]](../decisions/local-search.md), ADR-0009). 서버 3계약은 [[web-server-contracts]](../decisions/web-server-contracts.md)(ADR-0008, 불변 계승).

> **현재 코드 상태(2026-06-21)**: D26 로컬 검색·채팅 삭제는 구현 완료. 검색 결과는 날짜 lane이 기본이고, fact/date 질의는 `trip_summary` 카드가 lane 위에 보조 노출된다. 구현 이력: [[local-search-m3]](../impl-log/local-search-m3.md)·[[web-server-m1]](../impl-log/web-server-m1.md)·[[web-spa-m2]](../impl-log/web-spa-m2.md)(채팅 SPA — D26으로 superseded).

## 기동

```bash
EDDR_ROOT=/path/to/eddr eddr serve-api        # 기본 127.0.0.1:8000 (ADR-0008)
# SPA: web/dist 존재 시 / 에서 서빙 — cd web && npm run build
# M3부터 ANTHROPIC_API_KEY 불필요 — ollama(gemma4:e2b·qwen3-embedding:8b)만 필요
```

### 폰 접속 — Tailscale HTTPS (M2 확정)

전제: Mac·폰 둘 다 Tailscale 로그인(같은 tailnet), 폰은 이미 tailnet 경유 접속 가능.

```bash
tailscale serve --bg 8000        # 127.0.0.1:8000 → tailnet HTTPS 프록시(백그라운드)
tailscale serve status           # 발급 주소 확인: https://<기기명>.<tailnet>.ts.net
tailscale serve reset            # 해제
```

폰 Safari에서 `https://<기기명>.<tailnet>.ts.net` 접속. **serve-api는 127.0.0.1 바인딩 유지** — LAN 노출 불필요, HTTPS 종단은 tailscaled가 담당(ADR-0008 가드 그대로).

> 주의: tailnet IP(`http://100.x.x.x:8000`) 직접 접속은 비보안 컨텍스트라 브라우저가 현위치(geolocation)를 차단한다 — 반드시 ts.net HTTPS로.

## 목표 레이아웃 (prd v2 §6-a)

```
src/eddr/server/
  app.py                # create_app 팩토리 + SPA mount (유지)
  deps.py               # 전역 단일점 — engine·chat_lock 제거 → extractor·note_store (M3·M5)
  thumbnails.py         # photo_id 키 JPEG 캐시 (유지, 변경 없음)
  routes/
    map.py              # 신설 M2 — GeoJSON 일괄
    search.py           # 신설 M3 — 로컬 검색
    geocode.py          # 신설 M4 — Nominatim 프록시
    photos.py           # 확장 — by-date·no-location·location PUT·note
    status.py           # 확장 M6 — ollama 헬스
    chat.py             # 삭제 M3
web/src/
  store.ts              # 신설 M2 — zustand 1스토어 (지도 카메라 = 요청 객체 패턴)
  features/map/         # 신설 M2 — MapView(클러스터·고줌 썸네일 마커 ≤60)·useLongPress
  features/search/      # 신설 M3 — SearchBar·ResultsSheet·ResultLanes(DateLanes 개조)
  features/geocode/     # 신설 M4 — NoLocationBadge·Drawer·GeocodeFlow·ConfirmModal
  features/photos/      # Lightbox 유지(+NoteEditor M5)·DateDetailSheet 신설 M2
  features/chat/        # 삭제 M2
```

## API 표면 — 목표 전체 (prd v2 §6-b 권위, 요약)

| 구분 | 엔드포인트 | M |
|---|---|---|
| 신설 | `POST /api/search` · `GET /api/map/photos` · `GET /api/photos/by-date` · `GET /api/photos/no-location` · `GET /api/geocode/search` · `PUT /api/photos/location` · `PUT·DELETE /api/photos/{id}/note` | M2~M5 |
| 확장 | `GET /api/photos/{id}`(+좌표·location_source·note) · `GET /api/status`(+ollama) | M2~M6 |
| 유지 | `healthz` · `thumb` · `original` · `summary` · SPA 서빙 | — |
| 삭제 | `POST /api/chat` · `GET /api/chat/history` · `POST /api/chat/reset` | M3 |

## 핵심 흐름 (목표)

```
브라우저(SPA — 지도 홈)
   │ GET /api/map/photos (GeoJSON 5,587점 1회) → MapLibre cluster source
   │ POST /api/search {query}
   ▼
routes/search → QueryExtractor(gemma4:e2b) → QueryService(RRF) → KST 날짜 그룹·관련도순
   ▼
{interpretation(+answer_type), groups[{date, place, photos[+좌표]}], trip_summary[]}  → fact summary 카드 + lane 렌더 + 지도 하이라이트
   │ 사진 탭 → GET /api/photos/{id}/thumb?size=1280 (photo_id 간접 참조 — ADR-0008)
```

## 상태 모델

- 전역 `AppState` 1개(`deps.py`) — M3부터 engine·chat_lock·transcript 제거, extractor(+M5 note_store) 주입. 검색은 읽기 전용·무상태(락 불필요), 쓰기는 위치 지정·메모 2종뿐(멀티유저 전환점 — prd §6-e).
- 프런트: zustand 1스토어 — 모드(browse|search|dateDetail|geocode)·검색 결과·지도 카메라 요청(`{type:'flyTo', center, zoom, seq}` 소비 패턴)·드로어/모달 상태.

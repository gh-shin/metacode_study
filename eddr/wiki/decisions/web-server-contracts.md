---
title: "웹 API 서버 3계약 — server 위치·photo_id 간접 서빙·무인증 가드"
source: ["docs/adr/0008-web-server-contracts.md", "docs/prd.md"]
last_verified: 2026-06-11
status: fresh
confidence: high
tags: [web, server, fastapi, privacy, paths]
---

# 웹 API 서버 3계약 (ADR-0008)

D25 M1 착수 직전 고정한 **되돌리기 비싼 결정 3개**. 그 외 웹 설계 권위는 `docs/prd.md` §6.

## 1. server 패키지 위치

- `src/eddr/server/` — **기존 eddr 패키지 안**, 단일 pyproject·uv.lock (PRD 확정 ②).
- 전역 상태(엔진·서비스·락)는 **deps.py 단일점** — M5 멀티유저 전환 시 이 모듈만 교체.

## 2. photo_id 간접 서빙 + `EDDR_ROOT` resolve

- URL·요청 본문에 **파일 경로 절대 미수용** — `photo_id → DB image_path → resolve`만 (path traversal 원천 차단).
- API 응답에 절대경로 미노출 (ADR-0001 웹 확장).
- 상대 image_path(photos_library 8,574·takeout 1,385)는 **`EDDR_ROOT` 기준 resolve** — `--root` > `EDDR_ROOT` env > CWD. db·chroma·캐시 기본 경로도 여기서 파생 → 임의 디렉터리 기동.
- `/api/status.path_health`(최신 노출 표본 실존율)가 오설정 즉시 가시화 — M1 게이트.
- 썸네일 캐시 키 `{photo_id}_{size}.jpg` · size **{320, 1280} 화이트리스트만** · 전 포맷 공통 JPEG.

## 3. 무인증 기본 가드

- 기본 `127.0.0.1` 바인딩. LAN은 `--host` **명시 + 기동 경고**.
- 원격은 **Tailscale** 권장(M4) · 선택적 single shared token도 M4.
- **공개 인터넷 직노출(포트포워딩) 금지** — M5(인증) 전까지 불변.

## 불변 확인

- ADR-0003: 서버는 tool surface(5개)를 바꾸지 않음 — HTTP 레이어가 엔진을 wrap할 뿐.
- ADR-0001: 이미지 바이너리는 "내 서버 → 내 브라우저"만 흐름.

---
title: "D25 M2 — React SPA (web/) + 백엔드 표면 확장"
source: ["docs/prd.md", "docs/scenario.md", "docs/adr/0008-web-server-contracts.md"]
last_verified: 2026-06-11
status: fresh
confidence: high
tags: [web, spa, react, impl, m2]
---

# D25 M2 — React SPA 구현 (2026-06-11)

M1([[web-server-m1]](web-server-m1.md)) 위에 SPA와 M2 백엔드 표면을 얹었다.
**구현·로컬 E2E 완료 — 게이트(폰 브라우저 골든셋 9/10)는 사용자 검증 대기.**

## 백엔드 표면 (M2분)

- `GET /api/chat/history` — **서버측 표시용 사본(transcript)**: 엔진 `messages`(Anthropic
  포맷)를 노출하지 않고 `{role, text, photo_ids}`를 chat 성공 시 락 안에서 적재. 실패
  턴(busy·502)은 기록 안 됨. reset이 함께 비움. M3 영속화 시 이 리스트만 DB로 이동.
- `GET /api/photos/{id}/original` — 포맷 그대로 스트림 + `Content-Disposition`(basename만
  노출). duplicate는 canonical을 따른다.
- SPA 정적 서빙 — `create_app`이 `EDDR_ROOT/web/dist` 존재 시 `/`에 mount(html=True),
  `/api` 라우터 우선. dev는 Vite 프록시라 미사용.

## 프런트 (`web/`, 11파일 + lockfile)

- Vite 7.3.5 + React 19 + TS strict. **번들 gzip 62.8KB**(JS)·1.4KB(CSS). 프레임워크·상태
  라이브러리 없음(수제 CSS, 모바일 퍼스트, 다크모드 `prefers-color-scheme`).
- `src/api/client.ts` — **단일 클라이언트 모듈**(M5 토큰 주입점, prd §6-e 규율 ③). FastAPI
  `{detail}`을 사용자 메시지로 노출(busy 409 포함), 204 처리.
- `ChatPane` — busy 중 "답변 생성 중…" 말풍선(확정 ③: SSE 전 일괄 출력), 오류는 ⚠️ 말풍선,
  mount 시 history 복원 + 마지막 photo_ids 그리드 복원(FR-CHAT-2).
- `PhotoGrid` — 320px lazy 썸네일, 404 셀은 숨김(Gradio skip과 동일 의미).
- `Lightbox` — 1280px, 한 손가락 스와이프(JS)·핀치줌(브라우저 네이티브, `touch-action:
  pinch-zoom`)·키보드 ←→/Esc·날짜·장소 라벨(`api.detail`)·원본 저장 링크. viewport meta에
  maximum-scale을 안 둔 것이 핀치줌 전제.
- favicon은 인라인 SVG 이모지(📸) — 404 콘솔 에러 제거.

## 로컬 E2E — Playwright 390×844 (모바일 뷰포트)

| 항목 | 결과 |
|---|---|
| 초기 화면 | 헤더·힌트·입력바·푸터 "9,218/9,218 사진 인덱싱됨"(실 /api/status) |
| G10 "은하수 사진들 찾아줘" | 답변(몽골 2018-07 중심·2015~2022 분포 언급) + **그리드 20장** — ollama 백엔드 |
| 썸네일 | 3소스(local·photos_library·takeout) 20/20 전부 200 — EDDR_ROOT resolve 웹 경로 증명 |
| 전송량 | 그리드 1화면 **총 264KB(평균 13.2KB/장)** — NFR < 1MB의 1/4 |
| 라이트박스 | 라벨 "2018-07-16 · 위치 정보 없음"(GPS 무 구분, G10 reference 정합)·1/20·원본 저장 링크 |
| 새로고침 복원 | 대화 말풍선 + 그리드 20장 복원 PASS (FR-CHAT-2) |
| 새 대화 | 화면·서버 transcript 초기화 PASS · 콘솔 에러 0 |

## 후속 — 폰 첫 사용 피드백 2건 (2026-06-11 저녁)

1. **"답변은 나오는데 사진이 안 나옴"** — 로그 진단: R1(시점) 질문이 `list_trips`만 호출해
   photo_ids 0(M1 관찰 1과 동일 동작). **엔진 프롬프트에 사진 동반 지침 추가**(시점 답변
   전에 get_trip/`search_photos(trip_id)` 후속 호출) — ADR-0003 tool 불변, 프롬프트만.
2. **사진 영역 UI 재설계(사용자 확정)** — 평면 그리드 → **날짜별 lane**: 가로 스크롤,
   lane당 top 8 + "+N 더보기" 타일, 날짜·대표 장소·장수 헤더, 최신 날짜 우선(미상 맨 뒤).
   라이트박스는 lane 내 탐색. 데이터는 신설 `GET /api/photos/summary?ids=`(경량 배치,
   50개/요청·순서 유지·canonical 메타·캡션 N+1 없음 — `DateLanes.tsx`가 그룹핑).
   summary 라우트는 `/{photo_id}`보다 **먼저 등록**(경로 매칭 가로채기 방지).

## 게이트 (잔여 — 사용자)

**폰 브라우저(LAN) 골든셋 10문항 9/10** — 기준선은 1차 ollama 리포트(⑧ 연기 결정으로 실
API 불필요). 접속:

```bash
eddr serve-api --backend ollama --host 0.0.0.0   # LAN 노출 경고 출력됨
# 폰 Safari → http://<맥IP>:8000  (맥IP: ipconfig getifaddr en0)
```

통과 시 **Gradio 삭제**(확정 ⑤): `src/eddr/query/app.py` + `tests/query/test_app.py` +
pyproject `gradio` 의존 제거. 이후 M3(trips·enrichment·SSE).

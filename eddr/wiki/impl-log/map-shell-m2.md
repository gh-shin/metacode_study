---
title: "D26 M2 — MapLibre 지도 셸 + Tailscale HTTPS"
source: ["docs/prd.md", "docs/scenario.md", "docs/adr/0009-map-local-search.md"]
last_verified: 2026-06-12
status: fresh
confidence: high
tags: [impl-log, map, maplibre, web, tailscale]
---

# D26 M2 — MapLibre 지도 셸 (2026-06-12)

S1(지도 홈)·S3(날짜 상세) 구현. commits `ee8301e`(서버)·`7cc6289`(웹)·`3964d0a`(폰 피드백 3건)·`40b1135`(품질 리뷰 수정)·`257a25e`(chore).

## 서버 (`ee8301e`)

- `GET /api/map/photos` — 노출 GPS 5,587점 GeoJSON 전량(properties id·date만), `Cache-Control: private, max-age=300`, GZipMiddleware로 gzip **216KB 실측**(목표 150~250KB 적중)
- `GET /api/photos/by-date?date=` — KST 달력일(`substr(taken_at,1,10)` — M1 정규화 전제) 노출 사진 전부(GPS 무 포함), 형식 오류 422
- `GET /api/photos/{id}` 좌표 추가(ADR-0009 §3) — **PhotoSummary/PhotoDetail dataclass는 비변경**(privacy `fields()` 고정 테스트 유지, server 전용 repo 메서드 `exposed_gps_points`·`exposed_photos_by_date`로 우회. dataclass 확장은 M3에서)
- `thumb` 응답 `Cache-Control: private, max-age=86400, immutable`(`3964d0a` — photo_id 키 불변 전제, ADR-0002/0008)

## 웹 (`7cc6289`+`3964d0a`+`40b1135`)

- 스택 추가: maplibre-gl 5(OpenFreeMap liberty)·zustand 5. 번들 gzip **353KB**(수용)
- `store.ts` — mode(browse|dateDetail|clusterDetail)·cameraRequest **요청 객체 패턴**(`{type,…,padding,seq}` — 지도 인스턴스 비저장)·`selectionSeq`(시트 key 리마운트 — closing·스크롤 유출 차단)
- `MapView` — cluster source 3레이어, **고줌(≥14) 썸네일 마커 ≤60**(queryRenderedFeatures·id-diff 풀 — 팬 깜빡임 제거), 점 탭 ±22px bbox 히트(터치 표적 ~44px), 현위치 watchPosition+최신 사진 폴백, 주변 1.5x 버퍼 prefetch(rIC, 상한 60 — 실측 팬 후 추가 요청 0건)
- **클러스터 탭 = 줌인 없이 즉시 표출**(폰 피드백 ③): `getClusterLeaves(1000)` → 날짜 섹션 ClusterSheet("이 영역 N장·M일") → 날짜 헤더 탭 시 DateDetailSheet 전환. 줌은 더블탭/핀치에 위임
- `Sheet` 공용 셸 — **드래그 dismiss**(핸들·헤더 pointer 추종, >120px 또는 플릭 속도 판정 — 트레일링 저역 통과+정지 100ms로 "끌다 멈춤"은 복귀), slide-up/down 전환
- `DateDetailSheet` — by-date 그리드 + fitBounds(시트 높이 padding — 마커 가림 방지), Lightbox 재사용
- ChatPane·features/chat·client.ts chat 표면 삭제(백엔드 chat 라우트는 M3 일괄)

## Tailscale HTTPS (D26-④)

`tailscale serve --bg 8000` → `https://macbookpro.tail848f4e.ts.net` — **serve-api는 127.0.0.1 유지**(ADR-0008 가드 그대로, tailscaled가 TLS 종단). tailnet IP http 직접 접속은 비보안 컨텍스트라 geolocation 차단(기동 가이드는 [[web-app]] §기동). 폰 실검증: iPhone Safari에서 현위치→클러스터→시트→라이트박스→원본 전 구간 PASS(사용자 확인 2026-06-12).

## 리뷰

- 스펙 준수(fable): **PASS 0건 위반** — by-date GPS 무 포함·노출 필터·dataclass 비변경·범위 비침범 전수 확인
- 품질(fable): 승인 + 이슈 1건(시트 인스턴스 재사용 — `selectionSeq` key로 수정 `40b1135`). 관찰: GeoJSON 첫 fetch 실패 시 레이어 재시도 없음(저빈도)·LEAVES_CAP 하드코딩 drift — 백로그

## 검증 수치

pytest **241 passed** · Playwright 모바일 390×844 + 데스크톱 전 흐름 PASS(fitBounds 산술 검증 — 그 날짜 GPS 91점 전부 시트 비가림 영역) · 콘솔 에러 0 · 스크린샷 `screenshots/`(gitignored)

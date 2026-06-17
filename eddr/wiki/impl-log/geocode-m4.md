---
title: "D26 M4 — 위치 미상 워크플로(수동 지오코딩)"
source: ["docs/prd.md", "docs/scenario.md", "docs/adr/0009-map-local-search.md"]
last_verified: 2026-06-12
status: fresh
confidence: high
tags: [impl-log, geocode, nominatim, manual-location, web]
---

# D26 M4 — 위치 미상 워크플로 (2026-06-12)

S4(빨간 느낌표 → 일별 드로어 → 장소검색/long-press → 일괄 지정) 구현. commits `7227ace`(API)·`37849b5`(UI)·`56f8a4a`(리뷰 수정 4건).

## 서버 (`7227ace`)

- `no_location_day_groups()` — 노출 + `latitude IS NULL AND taken_at IS NOT NULL`, KST 일별 date DESC, 대표 photo_ids ≤4(taken_at순)·trip 최빈 힌트. **실측 2,867장/525그룹**(D26 확정 시 521 — M1 KST 정규화로 날짜 경계 이동)
- `NominatimClient.search()` — reverse 동형 골격(min_interval 1s **합산 공유**·식별 UA·accept-language=ko·jsonv2·limit 5·countrycodes 미지정). `GET /api/geocode/search` 서버 프록시(빈 q 422·GeocodeError 502)
- `PUT /api/photos/location {photo_ids[], latitude, longitude}` — 일괄 UPDATE(`location_source='manual'`+updated_at) 후 **주소는 기존 reverse 경로 통일**(quantize→캐시→셀 중심 reverse→upsert_geocode_cache→update_photo_geo, ADR-0009 §4). Nominatim 실패 시 좌표 저장 유지+address null — `photos_needing_geocode` 조건에 걸려 다음 `eddr geocode` 배치가 자가 치유. trips 자동 재계산 없음(토스트로 `eddr trips recompute` 안내)
- `location_source` 멱등 ALTER — VALID_SOURCES·INDEXING_STATUSES 비변경(hook 무관)

## 웹 (`37849b5`)

- `NoLocationBadge`(빨간 느낌표+잔여 그룹 수, 0이면 숨김) → `NoLocationDrawer`(일별 카드: 썸네일 4·trip 칩·진행 카운트) → `GeocodeFlow`(후보 ≤5 리스트+전용 지도 핀 source·후보 탭 flyTo zoom 14·"여기로 지정") → **long-press**(`useLongPress` — 650ms·8px 취소·contextmenu 폴백·geocode 모드만 부착) → `ConfirmModal`("{date} · N장 전체에 적용"+썸네일+주소 미리보기/"자동 조회") → 저장 후 배지·드로어 재조회 + `mapPhotos cache:'reload'` 강제 재요청
- store `'geocode'` 모드 — 시트 1개·selectionSeq·검색 컨텍스트 소멸 규칙 정합. 일괄 photo_ids는 by-date 재수집+`latitude===null` 필터(노출 필터 동일로 집합 정합)

## 리뷰 2단계 → 수정 (`56f8a4a`)

스펙 **7/7 ✅ 위반 0**(실DB manual 행 0 — 쓰기 없는 검증 확인 포함). 품질 리뷰 4건 수정:
- **C1 재적재 manual 좌표 리셋**: `upsert_photo`의 `latitude/longitude = excluded.*` 무조건 갱신이 GPS 무 사진의 수동 지정을 NULL로 되돌림(3중 모순 상태) → **`location_source='manual'`이면 좌표 보존 CASE**(사용자 의도 우선 — 이후 EXIF가 생겨도 manual 유지). 회귀 테스트 추가. **교훈: 수동 지정 컬럼은 enrichment 불가침 목록에 합류해야 함**
- I2 Nominatim rate limit 스레드 비안전(threadpool 병렬) → `threading.Lock`으로 reverse/search 발사 직렬화
- I3 long-press 핀치 오발화(두 번째 손가락이 primary 타이머 미취소) → non-primary pointerdown에서 `cancel()`
- I4 드로어 fetch 실패가 "없습니다 🎉" 허위 완료로 표시 → error 상태 분리

## Nominatim 실측 (스파이크)

"개심사" → 후보 5(1위 북한 명천 개심사, **서산 개심사 3위** — "서산 개심사"로 좁히면 정확) · "Eiffel Tower" → "에펠탑, …, 파리"(ko 표기). 한국 사찰·지명 커버리지 충분, 상호명 약점은 long-press 직접 지정이 1급 경로(설계 전제).

## 수치·잔여

pytest **257 passed** · Playwright 모바일 전 흐름(저장 직전 모달까지 — 실DB 쓰기 0 유지) PASS. **잔여 게이트(사용자)**: 폰에서 개심사 그룹 실지정(첫 manual 저장) → `eddr trips recompute` → 골든 **G06 → 10/10**.

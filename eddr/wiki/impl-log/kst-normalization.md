---
title: "D26 M1 — taken_at KST 정규화"
source: ["docs/adr/0009-map-local-search.md", "docs/prd.md", "src/eddr/db/source_loader.py"]
last_verified: 2026-06-12
status: fresh
confidence: high
tags: [impl-log, kst, timezone, data-surgery]
---

# D26 M1 — taken_at KST 정규화 (2026-06-12)

"하루 = KST 달력일"(ADR-0009 §6)의 데이터 기반. commit `afa4090`(본체) + `51f4584`(백업 수정).

## 진단이 기존 추정을 뒤집음

[[trip-clustering]] 시절 추정("photos_library = 촬영지 offset aware")이 실측으로 반박됨:

| source | 실측 포맷 | 행수 |
|---|---|---|
| photos_library | **전량 `+00:00` UTC aware** (μs 7,989건 포함) | 8,574 |
| google_takeout | 전량 `+00:00` UTC aware | 1,385 |
| local | 전량 naive (EXIF 벽시계, `2018-04-10T18:38:51`) | 806 (+NULL 924) |

UTC 인스턴트 정확성은 **시간대 히스토그램**으로 검증 — 한국 사진의 UTC 시각 피크 00~10시(= KST 주간 09~19시), 골 17~21시(= KST 새벽). local naive는 그대로 주간 분포 = 벽시계.

## 확정 규칙 (사용자 승인)

- aware → `astimezone(+09:00)` **인스턴트 보존**(μs 유지) · naive → `replace(tzinfo=KST)` **벽시계 보존** · NULL 불변
- 원본은 `taken_at_raw` 1회성 스냅샷("DB 최초 저장 표현" — [[db-schema]] 참조) + DB 파일 백업
- 로더 `_iso_or_none`에도 동일 정규화 — 재적재 drift 방지(upsert가 taken_at을 덮는 구조이므로 필수)

## 실행 결과 (실DB)

- 달력일 변경 **1,743장** = photos_library 1,016(11.8%) + takeout 727(**52.5%**) — 기대값 정확 일치. local 0(벽시계 보존이므로)
- `+09:00` 미부착 잔존 0 · Photos 앱 대조(자정 경계 한국 사진 5건, osxphotos) **5/5 일치**
- trips recompute: **83→82, 배정 3,760→3,777** — local 806건의 UTC 인스턴트 9h 교정(기존엔 KST 벽시계를 UTC로 오해석)에 따른 예상된 재배치
- 이후 `substr(taken_at,1,10)` = KST 달력일 — lane 그룹핑·by-date가 변환 없이 동작

## 트러블슈팅 기록 — sqlite3 backup 자기교착

리뷰 제안("잠금 쥔 채 `Connection.backup()`")을 그대로 적용하자 **쓰기 트랜잭션(BEGIN IMMEDIATE)을 쥔 연결 자신으로 backup()을 호출 → SQLite BUSY → CPython이 0.25s 간격 무한 재시도** = 저CPU 행. faulthandler 스택 덤프로 `cli.py:312` 특정, 최소 재현으로 확인.

**올바른 패턴**: 점유 잠금은 **별도 probe 연결**(BEGIN IMMEDIATE — 타 프로세스 쓰기 차단), 백업은 **새 읽기 연결**로 `backup()` — RESERVED(probe)와 SHARED(백업 읽기)는 타 연결 간 호환이라 일관 스냅샷이 재시작 없이 완료(실측 1ms). M4 쓰기 경로 등 향후 수술 CLI에 이 패턴 재사용.

## 테스트

suite **218 passed** — normalize 단위(aware μs 유/무·naive·멱등·None·+02:00·Z·무효 문자열 보존)·로더 경유·백필 CLI 통합(원본 보존·멱등 재실행·백업 유효성 행수 대조).

---
title: "인덱싱 파이프라인"
source: ["docs/PLAN.md#5", "docs/01_eda_findings.md#7", "docs/01_eda_findings.md#8"]
last_verified: 2026-06-11
status: fresh
confidence: high
tags: [indexing, pipeline, architecture]
---

# 인덱싱 파이프라인

`eddr index` 로 첫 인덱싱, `eddr update` 로 증분 처리.

---

## 단계 순서 (§5)

```
[1] osxphotos로 Photos Library 메타 + 경로 + persons 추출
    └─ 필터 제외: hidden / screenshot / document scan / <300×300 / burst non-keeper / video (D18)

[2] 로컬 폴더 file scan
    └─ ⚠️ 한글 폴더·파일명 NFC 정규화 필수 (macOS는 NFD 저장 — 미정규화 시 매칭 전부 실패, 03 실측·교정)

[3] content_hash(BLAKE3) + perceptual_hash(dHash) 계산 → cross-source dedup
    └─ ④ 구현: `eddr dedup backfill-hashes` → `eddr dedup mark`
       (duplicate_of 마킹, photos_library>local>google_takeout — PLAN §4.2)
    └─ near-duplicate 그룹화는 v1 보류 (ADR-0004)

[4] iCloud Optimize Mac Storage 사진 → on-demand 다운로드

[5] 좌표 → reverse geocoding (OSM Nominatim, 1 req/s, 캐시)
    └─ ④ 구현: `eddr geocode run` — 3dp 밀리도 양자화 geocode_cache,
       accept-language=ko, 셀 중심 요청, 연속 5회 실패 시 중단

[6] Daily Radius 추정 (격자 밀도 top-N) → setup wizard 사용자 confirm·편집 (D15)
    └─ ④ 구현: `eddr setup daily-radius` — 0.01° 격자 greedy 병합 후보 →
       대화형 라벨·반경 확정(전체 교체 저장). --propose-only는 후보만 출력

[7] Vision (로컬):
    ├─ 영어 caption 생성 (`gemma4:e2b` bulk, P3_hybrid 확정)
    ├─ caption text embedding (`qwen3-embedding:8b`) → Chroma sidecar
    └─ image embedding — 후속 검증(D20 image leg)

[8] Trip 클러스터링 (Daily Radius 외 + 24h 이상 연속, 다국가 1 trip 유지) (D14)
    └─ ⑥ 구현: `eddr trips recompute` — 전체 재계산(멱등), run 분리는 복귀 주신호
       + 사진 공백 72h 안전장치, 기간 내 no-GPS 동반 배정(PLAN §8), 영상 완전 제외,
       caption_done→trip_assigned 전이. trip_countries는 셀→캐시 ISO(거주국 제외)

[9] DB upsert (SQLite ledger) + Chroma vector upsert
```

---

## 핵심 운영 특성

### Recent-first 전략 (D22)
최근 1년치를 우선 배치 처리해 query 즉시 가능 시점을 당긴다. 나머지는 백그라운드로 계속 진행.

### Checkpoint (`indexing_status`)
각 단계 완료마다 `photos.indexing_status`를 갱신한다.

| 상태값 | 의미 |
|---|---|
| `meta_done` | [1]–[4] 완료 (현행 default) |
| `missing_image` | 메타는 있으나 Vision용 이미지 파일 미확보 |
| `skipped_video` | 영상 파일이라 Vision 단계에서 제외 |
| `caption_done` | [7] caption + caption_text embedding 완료(Chroma upsert 포함) |
| `trip_assigned` | [8] trip 클러스터 배정 완료 |
| `embed_done` | [7] image embedding 완료 — **후속 leg, 현재 미사용** |
| `pending` | 메타 미추출 — **설계상 정의, 현재 미사용**(현행 default는 `meta_done`) |

중단·재실행 시 `indexing_status`를 기준으로 완료된 단계를 skip한다.

### 증분 사이클
- `eddr update` — 신규·변경 사진만 처리
- `eddr update --recompute-trips` — trip 재클러스터링 포함

---

## iCloud–로컬 정합성 (02 실측)

사용자 로컬 아카이브의 **75.4%(icloud_new)가 iCloud에 없음** → D12(iCloud=SoT)·D16(Photos asset=identity)의 **경계조건**(로컬 전용 사진의 identity 처리는 ADR flag·미결). 로컬 EXIF는 **GPS 0.1% · date 46%**(png 편집본 결손)라, 위치·시간은 iCloud 매칭 또는 폴더명 컨텍스트에 의존. → findings §7.3·§7.4

## 인덱싱 제외 기준 (D18)

hidden, burst non-keeper, screenshot, document scan, video, 해상도 300×300 미만

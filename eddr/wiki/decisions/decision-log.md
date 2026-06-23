---
title: "결정 로그 D1–D26 (압축)"
source: ["docs/PLAN.md#3", "docs/01_eda_findings.md", "docs/adr/0009-map-local-search.md"]
last_verified: 2026-06-11
status: fresh
confidence: high
tags: [decisions, log]
---

## 결정 로그 (PLAN.md §3 기준)

| ID | 주제 | 결정 | 비고 |
|----|------|------|------|
| D1 | 사용자 범위 | 본인 1명 (개인 도구) | 멀티테넌시·인증 없음 |
| D2 | MVP 스코프 | 메타데이터 + Vision 캡션/임베딩 | 얼굴 인식은 자체 안 함 |
| D3 | Vision 처리 위치 | 전부 로컬 (M4 Pro 64GB) | bootstrap 환경으로 충분 |
| D4 | 사진 Source of Truth | iCloud/Photos Library 그대로, EDDR은 참조 | EDDR은 파생 데이터만 소유 |
| D5 | 답변 LLM | Claude API | **D26으로 폐기** — 런타임 외부 LLM 0회, 질의 해석은 gemma4:e2b 로컬 |
| D6 | Privacy 경계 | 텍스트(메타+캡션)만 API로, 이미지는 절대 전송 안 함 | 정밀 좌표·PII는 미전송 → [privacy](privacy.md) |
| D7 | UI 형태 | 로컬 Gradio 채팅 웹 UI | D25(채팅 SPA)를 거쳐 **D26(지도 검색 SPA)으로 대체** |
| D8 | 인덱싱 사이클 | 1차 batch 후 점진적 업데이트 | near-dup 그룹핑 v1 보류(ADR-0004); 02 실측 919쌍·0.061% → [eda-scope](eda-scope.md) |
| D9 | 동영상 | 제외 (사진만) | v2 후보 |
| D10 | 인물 데이터 | Photos.app Persons named만 import | 데이터 적재 유지, person 질의는 ADR-0004로 폐기 → [eda-scope](eda-scope.md) |
| D11 | Trip 모델 | 자동 세그멘테이션 + `trips` 테이블 1등급 단위 | GPS + 시간 갭 기반 |
| D12 | iCloud Optimize 처리 | 인덱싱 시 on-demand 다운로드, dirty 유지 | macOS가 관리 |
| D13 | 완료 기준 | 골든셋 10문항 중 8개 이상 만족 | 손으로 작성 |
| D14 | Trip 정의 | 일상 반경 외 24h 이상, 다국가도 1 trip (`trip_countries` M2M) | 1박 2일 trip도 인정 |
| D15 | Daily Radius | KDE 자동 클러스터링 → 사용자 setup wizard confirm·편집 | 다중 영역 (집/직장/본가) |
| D16 | Photo identity | Photos.app asset이 정체성 SoT | 원본+보정본 = 1 photo → [photo-identity](photo-identity.md) |
| D17 | iCloud Shared Library | 포함 (owner 무관) | 가족 추가 사진도 in scope |
| D18 | 인덱싱 제외 | hidden, burst non-keeper, screenshot, document scan, video, <300×300 | |
| D19 | Caption v1 | 영어 1개만, multilingual embedding이 한국어 query 처리 | 03 검증 **PASS**(recall@10 0.70)·프롬프트 **P3_hybrid** 확정 → [model-decisions](../models/model-decisions.md) |
| D20 | Embedding | 사진당 2개 (`image` + `caption_text`), single model | caption_text는 Chroma sidecar 채택(ADR-0006), image leg 미검증(후속) |
| D21 | LLM tool surface | 5개 structured tools, freeform SQL 없음 | **ADR-0009로 superseded** — QueryService는 내부 검색 서비스로 존속 → [tool-surface](tool-surface.md)(archived)·[local-search](local-search.md) |
| D22 | Indexing UX | Recent-first batch → background continue, status checkpoint | 첫 query 가능 시점 단축 |
| D23 | Golden set 구조 | R1:5/R2:3/R3:2, hybrid eval, 정답 형식 query별 혼합 | 분포는 사용자 선별로 R1 2/R3 7/복합 1 확정(2026-06-11). **채점은 D26-⑤로 검색 결과 자동 채점(v2) 전환** |
| D24 | 데이터 부재 보강 | 검색 내부 불변, 날짜 그룹 → 사용자 문답 → 파생 데이터 업데이트 | G06류 해소(2026-06-11). **D26으로 흡수** — 수동 지오코딩(S4)·사진 메모(S5)가 구현 형태, wizard·채팅 문답은 미구현 폐기 |
| D25 | 웹 서비스화 | 자가호스팅 개인 웹 앱 — FastAPI+React SPA, Gradio(D7) 대체, 모노레포 재구성 | 2026-06-11. M1(API)·M2(채팅 SPA) 구현 후 **UI 패러다임은 D26으로 교체** — 서버 인프라(ADR-0008)·SPA 자산 계승 → [web-server-contracts](web-server-contracts.md) |
| D26 | 지도 중심 로컬 검색 전환 | **채팅 폐기·검색 전용** — 지도 홈(MapLibre+OpenFreeMap)·자연어 검색(gemma4:e2b 해석, 외부 LLM 0회)·수동 지오코딩(Nominatim /search·long-press·`location_source`)·사진 메모(임베딩 합류)·taken_at KST 정규화 | 2026-06-11 사용자 확정 8건(prd v2 §4). ADR-0009(ADR-0003 supersede·ADR-0001 amend). 골든셋은 검색 결과 자동 채점 → [local-search](local-search.md) |

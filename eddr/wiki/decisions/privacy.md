---
title: "Privacy 경계"
source: ["docs/adr/0001-privacy-boundary.md", "docs/adr/0009-map-local-search.md", "docs/PLAN.md#D6"]
last_verified: 2026-06-11
status: fresh
confidence: high
tags: [privacy, pii, llm-tool]
---

## 결정 요약

외부 LLM API로 전송하는 데이터의 경계를 명시한 결정. PLAN.md D6("이미지는 절대 전송 안 함")에서 출발해 텍스트 데이터의 세부 경계까지 확정. **ADR-0009(D26)로 보강(amend)**: ① 런타임 외부 LLM 호출 자체가 0회가 되어 아래 "전송 가능" 목록은 사실상 휴면 ② 경계의 본질은 "외부 LLM 미전송" — **정밀 좌표의 "내 서버 → 내 브라우저" 전송은 허용**(지도 렌더용, ADR-0008 무인증 가드가 노출 경계) ③ 수용한 외부 의존 2건: 지도 타일 서버(열람 타일 좌표)·Nominatim(장소 검색어/지정 좌표, 서버 프록시만).

## LLM에 전송 가능한 데이터

- `taken_at` (촬영 시각)
- reverse geocode 결과: `country`, `city`, `district` (도시 단위까지)
- `person.name` (named persons, hidden person 제외)
- caption 텍스트 전체
- 기본 EXIF: `width`, `height`, `camera_make`, `camera_model`
- trip 메타: id, name, dates, top persons

## 외부로 절대 내보내지 않는 데이터

- **raw image 바이너리** (D6) — 외부 서비스 일체 경유 금지(웹 확장: "내 서버 → 내 브라우저"만, prd §5 계승)
- **Photos.app hidden 사진**: 인덱싱 단계부터 제외 — DB에 아예 없음.
- **camera serial 등 PII EXIF**
- **파일시스템 절대경로** (ADR-0008 — photo_id 간접 참조만)
- **정밀 좌표 (`latitude`, `longitude`)의 외부 전송** — 단 D26부터 **내 브라우저로의 노출은 허용**(위 결정 요약 ②). Nominatim reverse/지정 좌표 전송은 종전대로 수용 범위.

## 구현 강제 방식

검색 서비스 응답 dataclass(구 ADR-0003 tool schema에서 계승)가 외부 노출 필드를 통제하고, D26부터는 **런타임 외부 LLM 경로 자체가 없다**(anthropic 의존 제거 — 구조적 강제). 좌표는 지도·검색 응답 등 로컬 브라우저 전용 API에만 실린다.

## 주요 트레이드오프

- "내 집 근처 카페" 같은 근거리 query는 EDDR 로컬에서 거리 계산 후 후보 사진만 LLM에 전달하는 우회 처리 필요.
- `person.name`은 LLM에 전송됨 — 단일 사용자 개인 도구라는 가정에 의존. v2 multi-user/cloud 배포 시 재검토 예정.
- Hidden 사진을 숨긴 상태에서 `eddr update` 실행 시 영원히 모름. hide 해제 후 다음 `eddr update`에서 신규 사진으로 처리 (의도된 동작).

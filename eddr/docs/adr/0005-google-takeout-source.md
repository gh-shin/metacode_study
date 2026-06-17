# ADR-0005: Google Takeout을 3번째 데이터 소스로 추가 — 날짜 구간 gap-fill

## Status

Accepted (2026-06-03)

## Context

사용자의 Google Photos에 맥 Photos Library에는 없는 과거 사진이 다수 존재할 것으로 추정된다. 목적은 **"맥에 없는 사진 확보"**(커버리지 빈틈 메우기)이며, 같은 사진을 다시 가져오는 것이 아니다.

**접근 경로 조사 (2026-06 기준):**

- 2025-03-31, 구글이 Photos Library API의 전체 라이브러리 읽기 스코프(`photoslibrary.readonly` 등)를 **소급 삭제**했다. OAuth 앱은 더 이상 사용자의 기존 사진을 열거할 수 없다 (앱이 직접 올린 미디어 + Picker로 수동 선택한 항목만 접근 가능).
- Picker API는 매 세션 수동 선택이라 수천 장 자동 인덱싱에 부적합하다. `rclone`(Google Photos backend)·`gphotos-sync`도 같은 이유로 무력화/아카이브되었다.
- → **Google Takeout(수동 일괄 익스포트)이 유일한 현실적 경로다.** (2026-06-01 도입된 incremental Takeout 스케줄로 주기적 갱신은 일부 가능.)

**Takeout 데이터 특성:**

- 메타데이터가 이미지 EXIF가 아니라 **JSON 사이드카**(`*.supplemental-metadata.json`)에 분리된다 (`photoTakenTime`·`geoData`·`description`·`people`). 구글이 EXIF를 수정/제거할 수 있어 **시각·GPS는 JSON이 권위 소스**다.
- 연도 폴더와 앨범 폴더에 **동일 파일이 중복** 포함된다 (바이트 동일).
- 파일명 46자 잘림·분할 zip·`-edited` 사본 등 잔버그가 있다.
- Original Quality 업로드는 원본 바이트 보존, Storage Saver는 JPEG 재인코딩 + EXIF 손실.

**기존 결정과의 관계:**

- **ADR-0001(프라이버시):** 경계는 *송신*(Claude API로 내보내는 데이터) 통제이지 *수신* 금지가 아니다. 외부 소스에서 읽어오는 것 자체는 위반이 아니며, 수집된 사진도 동일 송신 규칙(정밀좌표·원본이미지 미전송)을 따른다.
- **ADR-0002 / D4·D16(정체성):** `source` + `source_uri`로 다중 소스를 이미 표현할 수 있다. Photos Library가 SoT라는 원칙은 유지되고, Takeout은 *맥에 없는* 사진만 채운다.
- **ADR-0004 / D8(near-dup 보류):** — 핵심. 수집 범위를 맥 Photos Library와 **날짜로 분리**하면 교차 소스 중복이 원천적으로 발생하지 않아, 보류 중인 near-dup 결정을 건드릴 필요가 없다.

**검토 옵션:**

- (a) Photos Library API/OAuth로 직접 수집 — 2025-03 정책 변경으로 **불가**
- (b) Takeout 전량 수집 후 해시/perceptual dedup으로 맥과 병합 — near-dup(ADR-0004 보류) 재개 필요, 재인코딩 시 dedup 불완전, 비용 큼
- (c) **Takeout에서 `[2011, C)` 날짜 구간만 수집(C = 맥 보관함 시작일), 맥과 날짜 분리로 dedup 우회 — 채택**

## Decision

**구글 Takeout을 3번째 데이터 소스(`source = 'google_takeout'`)로 채택한다.**

- **정체성:** `source_uri` = Takeout 내 상대 경로 (사이드카에 구글 미디어 키가 있으면 함께 보존).
- **수집 범위:** `taken_at ∈ [2011-01-01, C)`. C = 맥 Photos Library의 조밀 커버리지 시작일이며 **osxphotos 실측으로 확정**한다 (구현 1단계). `2011`은 사용자 지정 하한.
- **dedup:** 맥과 날짜 분리이므로 **교차 소스 dedup·perceptual hash는 v1 미적용** (ADR-0004 보류 유지, 미변경). Takeout *내부* 중복(연도↔앨범 폴더)만 BLAKE3 정확일치로 1장 보관.
- **메타 권위:** 시각·GPS는 JSON 사이드카 우선, EXIF 폴백.
- **획득:** Takeout 수동 다운로드 → `data/google_photos/raw/`. (Drive API 자동화·incremental Takeout은 범위 밖, 후속 후보.)
- **이번 단계 산출물:** `data/google_photos/staged/` + `manifest.jsonl`까지의 **적재(staging)**. 메인 인덱싱 DB 통합은 메인 파이프라인 완성 후 별도 단계.

데이터 여건 변화 시 재검토 가능한 결정이며 영구 결정이 아니다.

## Consequences

**Positive:**

- 맥에 없는 과거 사진으로 커버리지를 확장하면서, 데이터 정합성 결정(ADR-0004)을 변경하지 않는다.
- 날짜 분리로 dedup 복잡도를 제거한다 (YAGNI, ADR-0003 정신과 일관).
- 소스 추상화(`source`/`source_uri`)의 첫 실증 케이스 → 향후 소스 확장 패턴 검증.

**Negative:**

- Takeout은 수동·지연(구글 처리시간 수십 분~수시간)이며 실시간 동기화가 없다.
- Storage Saver 업로드면 재인코딩·EXIF 손실 → 일부 사진 화질·메타 저하 (JSON 사이드카로 메타는 일부 복구).
- **`[2011, C)` 밖(= 맥 보관함 시작 이후)의 "구글 전용" 사진은 이번 범위에서 누락된다** — 겹침 회피를 위한 의도적 트레이드오프. 필요 시 후속 세션에서 보강.
- C 경계 부근 또는 맥의 산발적 과거 사진과 소규모 중복 가능 (무시 가능 수준, 모니터링).

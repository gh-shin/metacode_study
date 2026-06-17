# ADR-0008: 웹 API 서버 3계약 — server 패키지 위치 · photo_id 간접 서빙 · 무인증 가드

## Status

Accepted (2026-06-11)

## Context

D25(웹 서비스화 — 자가호스팅 FastAPI+React, PLAN §3)가 확정되고 설계 권위는 `docs/prd.md`에 있다. PRD `[확정 ⑥]`에 따라 본 ADR은 M1(API 서버) 착수 직전, **구현 후 되돌리기 비싼 결정 3개만** 추출해 고정한다. 그 외 미세 설계(SSE 시점, 대화 영속화 등)는 prd.md §6이 권위다.

실측 근거 (2026-06-11, `data/eddr.sqlite`):

- `image_path` **상대경로 9,959건**(photos_library 8,574 · google_takeout 1,385 — repo 루트 기준), `local` 1,730건은 절대경로. 현 Gradio `eddr serve`는 CWD 의존이라 repo 루트 밖에서 사진이 깨진다 → 데몬화(launchd, M4) 불가.
- 기존 썸네일 캐시 키는 `sha1(경로)[:24]`(`query/app.py:_thumbnail`) — 파일 이동·경로 정리 시 캐시 전체가 무효화되고, 브라우저 호환 포맷은 원본 풀사이즈 직서빙이라 모바일 전송량이 크다.
- 무인증 MVP이므로 서버가 노출되는 범위 = 사진 원본이 노출되는 범위다.

## Decision

### 1. server 패키지 위치 — `src/eddr/server/` (기존 패키지 안)

- FastAPI 서버는 **기존 `eddr` 패키지 안** `src/eddr/server/`(app.py 팩토리 · deps.py · thumbnails.py · routes/)에 둔다. 단일 pyproject·uv.lock 유지.
- 전역 상태(엔진·서비스·락)는 **`deps.py` 단일점**에만 둔다 — 멀티유저 전환(M5) 시 이 모듈만 세션 스코프로 바꾼다(prd §6-e 규율 ①).
- M5에서 경계 물리 분리(별도 패키지)로 승격할 수 있다 — 그때까지 코어 모듈을 직접 import한다.

### 2. photo_id 간접 서빙 + `EDDR_ROOT` resolve 계약

- **URL·요청 본문 어디에도 파일 경로를 받지 않는다.** 사진 서빙은 `photo_id → DB image_path → resolve` 간접 참조만 — path traversal이 입력 단계에서 원천 차단된다.
- **API 응답에 파일시스템 절대경로를 노출하지 않는다** (ADR-0001의 웹 확장 조항, prd §5).
- resolve 규칙: `image_path`가 절대경로면 그대로, 상대경로면 **`EDDR_ROOT` 기준**으로 푼다. `EDDR_ROOT`는 `--root` 플래그 > `EDDR_ROOT` 환경변수 > CWD 순으로 정해지며, db·chroma·썸네일 캐시 기본 경로도 여기서 파생한다 → **임의 디렉터리 기동** 가능(CWD 의존 제거).
- `/api/status`의 `path_health`(노출 사진 최신 표본 resolve 실존율)가 오설정을 즉시 가시화한다 — M1 수용 게이트.
- 썸네일 캐시 키는 `{photo_id}_{size}.jpg`, size는 **{320, 1280} 화이트리스트 2단계만**. 전 포맷 공통 JPEG 변환(브라우저 호환 포맷 포함 — 모바일 전송량 절감).

### 3. 무인증 기본 가드

- 기본 바인딩 **`127.0.0.1`**. LAN 노출은 `--host` **명시 + 기동 경고 출력**이 계약.
- 원격 접근은 **Tailscale**(tailnet 내 노출, 인터넷 비공개) 권장 — M4. 선택적 single shared token(Bearer 1개, "회원가입 아님")도 M4.
- **공개 인터넷 직노출(포트포워딩) 금지** — 무인증 API가 사진 원본·대화 엔진을 그대로 서빙하기 때문. 이 항은 M5(인증 도입) 전까지 불변.

## Consequences

**Positive:**

- CWD 비의존 → launchd 상시 기동(M4) 경로가 열린다. TODO 코드품질 "image_path 표기 통일" 항목이 이 계약으로 흡수·해소.
- photo_id 키 캐시는 파일 이동·경로 정리에 안정적이고, size 화이트리스트가 캐시 폭주(임의 size 요청)를 차단한다.
- 전역 상태 단일점·경로 미노출·간접 서빙은 M5 멀티유저 전환 시 그대로 유지되는 규율이다.

**Negative / 수용한 리스크:**

- 기존 sha1 키 썸네일 캐시는 1회 폐기된다(재생성 비용 — lazy + single-flight로 흡수, prd §9).
- `EDDR_ROOT` 오설정 시 상대경로 사진 전체가 미서빙 — path_health로 즉시 드러나는 실패로 설계.
- 무인증인 한 같은 네트워크의 누구나 접근 가능 — 신뢰 홈 LAN 전제(ADR-0007과 동일한 수용), 그 밖은 Tailscale로 경계.

## 관련

- 상위 결정: **D25**(PLAN §3) · 설계 권위: `docs/prd.md` §5·§6 — 본 ADR은 그 중 되돌리기 비싼 3건만 고정
- 확장: **ADR-0001**(privacy — 절대경로 미노출·"내 서버→내 브라우저"만) · 불변: **ADR-0003**(5 tools — 서버는 tool surface를 바꾸지 않음)
- 구현: `eddr serve-api`, `src/eddr/server/` (M1)

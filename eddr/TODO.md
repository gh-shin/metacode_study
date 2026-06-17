# EDDR TODO

> **이 파일은 "무엇이 남았나(미완료)"만 추적**한다. 완료 항목은 즉시 [`TODO_ARCHIVE.md`](TODO_ARCHIVE.md)로 이관(날짜·시각 분단위 + commit hash). 이관 규약: [`AGENTS.md` §7 ARCHIVE](AGENTS.md).
> 설계 상세·결정의 권위(SoT)는 링크된 문서에 있다 — 내용을 여기 복붙하지 말고 링크로 위임할 것.
> SoT: [`docs/PLAN.md`](docs/PLAN.md) · 용어: [`CONTEXT.md`](CONTEXT.md) · 결정: [`docs/adr/`](docs/adr/) · EDA 리포트: [`docs/01_eda_findings.md`](docs/01_eda_findings.md)
> 최종 갱신: 2026-06-15 16:55

## 🔨 빌드 순서 — [PLAN.md §10](docs/PLAN.md)
순서대로 진행, 각 단계 완료 시 [`TODO_ARCHIVE.md`](TODO_ARCHIVE.md)로 이관.

- [ ] **① 골든셋 10문항 — 선별 완료(2026-06-11), 사용자 확정만 잔여** — 사용자 선별 Q1·4·5·9·10·25·31 + 신규 3문항 → `docs/golden_set.yaml` 작성·커밋(`1396bde`, `confirmed: pending`). 잔여: 기대 정답(expect) 검토 후 `confirmed` 확정. **D26-⑤로 채점 체계가 검색 결과 자동 채점(v2)으로 전환** — M3에서 v2 스키마(기계 판정 match 규칙) 제공 시 문항별 규칙 작성도 사용자 몫(골든셋 규약). 구 ⚠️ 하위 2건(persons 명세·타임존 정책)은 ADR-0009·D26-⑧로 종결 → ARCHIVE. → [impl-log](wiki/impl-log/golden-regression.md)
- ✅ **② 프로젝트 스켈레톤 — 완료** (2026-06-08) → [TODO_ARCHIVE](TODO_ARCHIVE.md)
- ✅ **③ 인덱싱 1단계 — 완료** (2026-06-10) → [TODO_ARCHIVE](TODO_ARCHIVE.md)
- ✅ **④ dedup + geocode + Daily Radius + setup wizard — 완료** (2026-06-10) → [TODO_ARCHIVE](TODO_ARCHIVE.md) · [impl-log](wiki/impl-log/dedup-geocode-radius.md)
- ✅ **⑤ Vision — 완료** (2026-06-08): caption 9,383(영어·P3_hybrid) + 임베딩(Chroma 9,383 정합). **후속(06-14): 음식 strand 1,393장 큰 모델 재캡션·재임베딩**(gemma4:31b 995/qwen3-vl:8b 398, 100% 정합 → ARCHIVE) → [TODO_ARCHIVE](TODO_ARCHIVE.md) · [ADR-0007](docs/adr/0007-lan-distributed-vision.md)
- ✅ **⑥ Trip 클러스터링 — 완료** (2026-06-11): 83 trips·배정 3,760 → [TODO_ARCHIVE](TODO_ARCHIVE.md) · [impl-log](wiki/impl-log/trip-clustering.md)
- ✅ **⑦ Gradio UI + Claude API + 5 tools — 완료** (2026-06-11): 서비스 동작 검증. **D26으로 Claude 경로·Gradio는 폐기 예정(M3)** — 검색 코어(QueryService)는 계승 → [TODO_ARCHIVE](TODO_ARCHIVE.md) · [impl-log](wiki/impl-log/query-service.md)
- [ ] **⑧ 골든셋 회귀 검증 — 1차 ollama 9/10 완료(Done ≥8 충족), 체계 전환 잔여** — 러너·1차 채점(대행 `feea6aa`)·검색품질 개선 반영 완료. 잔여: ⓐ (사용자) 대행 채점 결과 최종 확인 + `golden_set.yaml` confirmed 확정(①과 동일 건). ⓑ 2차 실 Claude API 채점은 **공식 폐기**(ADR-0009 §2 — 채점 대상 ChatEngine 소멸) → ARCHIVE. 이후 회귀는 **D26 M3의 v2 자동 채점**(`eddr golden` → `POST /api/search`)으로 대체. → [impl-log](wiki/impl-log/golden-regression.md) · [검색품질](wiki/impl-log/retrieval-quality.md)

## ⏭️ 다음 세션 진입점 — 2026-06-15 (성능·코드 정리 세션)
1. **D26 M3~M5: 구현·리뷰 완료, 게이트만 잔여** — (사용자) 골든셋 `confirmed` 확정 + **golden match 규칙 작성** + 폰 수동 지오코딩 → `eddr golden` 10/10 회귀(아래 D26 백로그).
2. **성능·코드 정리 완료(2026-06-15)** — 문서/저장소 정합화·graphify 재인덱싱 + 코드 정리 4건(index_errors·모델명 상수화·caption N+1·golden CLI 테스트) 전부 커밋·테스트 328 green → ARCHIVE.
3. **RAG 품질 개선** — 별도 보류 트랙(아래 🔎 섹션).

## 🗺️ D26 지도 중심 로컬 검색 전환 — 마일스톤 백로그 (2026-06-11 확정)
근거: [PLAN.md §3 D26](docs/PLAN.md) · [ADR-0009](docs/adr/0009-map-local-search.md) · SoT: [scenario.md v2](docs/scenario.md)(S1~S9) · [prd.md v2](docs/prd.md)(FR·D26-①~⑧·M0~M6)
> 구 D25 백로그(M2 게이트 폰 골든셋·M3 trips/enrichment/SSE·M4 원격)와 구 D24 백로그(enrich wizard·채팅 문답)는 **D26으로 supersede·흡수** → ARCHIVE. D25 M1·M2 구현 자산은 계승.

- ✅ **M0 문서 개정 — 완료** (2026-06-12, 사용자 리뷰 승인) → [TODO_ARCHIVE](TODO_ARCHIVE.md)
- ✅ **M1 taken_at KST 정규화 — 완료** (2026-06-12) → [TODO_ARCHIVE](TODO_ARCHIVE.md) · [impl-log](wiki/impl-log/kst-normalization.md)
- ✅ **M2 지도 셸 + Tailscale HTTPS — 완료** (2026-06-12, 폰 검증 PASS + 피드백 3건 반영 + 리뷰 2단계 통과) → [TODO_ARCHIVE](TODO_ARCHIVE.md) · [impl-log](wiki/impl-log/map-shell-m2.md)
- [ ] **M3 로컬 검색 + 채팅 일괄 삭제 — 구현·리뷰 완료, 게이트만 잔여** — 본구현 4커밋(`0ca9ddd`·`7533de3`·`2bd631a`·`04d515e`) + 리뷰 수정(`d6a2212`, **C1 KST 날짜 경계 시프트** 포함). 스펙 7/7 ✅·품질 승인·240 passed·외부 LLM 0회 달성·503 검증 완료. **잔여 = (사용자) golden match 규칙 작성**(보류 리포트 PDF 전송됨) → `eddr golden` 9문항 중 8↑(G06 제외). → [impl-log](wiki/impl-log/local-search-m3.md)
- [ ] **M4 위치 미상 워크플로 — 구현·리뷰 완료, 게이트만 잔여** — API(`7227ace`)·UI(`37849b5`)·리뷰 수정 4건(`56f8a4a` — **재적재 manual 좌표 보존 C1** 포함). 스펙 7/7 ✅·257 passed·실측 525그룹/2,867장. **잔여 = (사용자) 폰에서 개심사 그룹 실지정**(첫 manual 저장) → `eddr trips recompute` → **G06 = 10/10**. → [impl-log](wiki/impl-log/geocode-m4.md)
- [ ] **M5 사진 메모 — 구현·리뷰 완료, 게이트는 골든 회귀와 동시** — API(`62425ba`)·NoteEditor(`97eed12`)·리뷰 수정 4건(`09b436c` — note leg 거리 경쟁 정밀 보정·2,000자 캡). 스펙 ✅+편차(거리 경쟁 정규화) 승인·271 passed·실DB 가역 E2E PASS(rank 1 합류·흔적 0). **잔여 = 골든 10/10 회귀 채점**(사용자 match 작성 후 M3 게이트와 일괄). → [impl-log](wiki/impl-log/notes-m5.md)
- [ ] (선택) **M6 운영 마감** — launchd·status ollama 헬스·실측 기록·wiki INGEST. 백로그: 메모 LIKE leg·영어 임베딩 질의 A/B·PMTiles 오프라인·날짜 미상 764장·name:ko 스타일·사진별 일괄 제외·embedded:false 재임베딩 배치·모델 교체 시 note 재임베딩

## 🔎 RAG 품질 개선 트랙 (별도 트랙)
근거: [통합 리포트](reports/rag_quality/ASSIGNMENT_REPORT.md) · E2E 골든 **10/10 달성**(2026-06-15, G08 날짜질의 라우터 완료 → ARCHIVE). 잔여:
- [ ] **broad keyword 가중 조정** — `food`(DF 1,066)·`temple`·`flower`·`travel` lexical leg 가중 하향(RRF가 오캡션까지 증폭해 기각된 근본 원인). (M)
- [ ] **재캡션 전/후 RAG 수치화** — GT가 e2b 고정이라 큰 모델 재캡션의 RAG 효과 미측정. 큰모델-GT로 microbench+golden 재비교. (M)
- [ ] (선택) **비음식 재캡션 확장** — 음식과 동일 분리 파이프라인(`--no-vector`+`reindex-vectors`). 전량 gemma31b ~130h. (L)
- [ ] (정책) **포스터/문서 속 음식명 false positive** — `text_poster_only` 분리 bucket/검색정책(사용자 판단 권장).

## 🌐 Google Takeout 3번째 소스 (ADR-0005) — 적재 파이프라인
근거: [ADR-0005](docs/adr/0005-google-takeout-source.md) · [impl-log](wiki/impl-log/google-takeout-staging.md)
> 빌드(Task 1–6) + 실데이터 적재(Task 7, **1,385장**)는 완료·이관 → [TODO_ARCHIVE](TODO_ARCHIVE.md). 메인 DB 통합은 메인 파이프라인(③+) 이후 별도.

- [ ] (선택) `ingest` CLI에 `--source-dir` 추가 — macOS 자동압축해제 레이아웃(`raw/`에 연도 폴더 직접) 자가 재실행용. 현재는 `ingest()` 직접 호출로 실행함.
- [ ] (보류) RAW(NEF 9)·영상(mp4 82) 인제스트 — 실측 완료(전량 net-new이나 순증 9장·메타 무가치·신규 EXIF 의존성 필요). 사용자 보류(2026-06-04). 재고: vision 단계(⑤)/비중 증가 시. → [impl-log](wiki/impl-log/google-takeout-staging.md)

## 🔬 EDA 후속 (별도 세션 — 메타데이터 vs 픽셀 vs 컴퓨트 분리)
근거: [`docs/01_eda_findings.md` §4·§7](docs/01_eda_findings.md)

- [ ] **D14 Trip 심화** (메타데이터, 로컬파일 불필요) — 전체 trip 프로파일(⑥ 실측 83개) · 파라미터 민감도(`--min-duration-hours 24`·`--max-gap-hours 72` 기본의 경계: 1박2일<24h 누락·연속 이틀 외출 가짜 trip) · 경계 품질. no-GPS 배정은 ⑥ 기간 배정으로 758장 1차 해소 — **잔여 위치 미상의 본 해소는 D26 M4(수동 지오코딩)**. → [§3.4/§3.6](docs/01_eda_findings.md) · [impl-log](wiki/impl-log/trip-clustering.md)

### ⏭️ 다음 세션 후보 (이미지 임베딩·정합성·ADR 결정)
> Vision 캡션(caption_text 경로)은 **03 완료**(D19 PASS·P3_hybrid). 아래는 그 후속 + 02 미결.
- [ ] **D20 이미지 직접 임베딩 경로(image leg) 검증** — 캡션텍스트 경로(caption_text leg)는 **03에서 PASS**(P3_hybrid·recall@10 0.70). 이미지를 직접 임베딩(SigLIP/CLIP/Qwen3-VL-Embedding)하는 경로는 미검증 — 캡션검색 지명약점(제주·일산) 보완 가능성. D26에서는 수동 지오코딩(M4)·메모(M5)가 같은 약점을 먼저 공략 — image leg는 그 후 재평가. → [§8.6](docs/01_eda_findings.md)
- [ ] **정합성 timestamp 매칭** — overlap 24.6%는 파일명 기준 하한; EXIF/iCloud 촬영시각 근접으로 리네임 파일까지 매칭 정밀화(icloud_new 과대 보정). → [§7.3](docs/01_eda_findings.md)
- [ ] ⚠️ **ADR flag 3건 결정**(사용자) — ①규모 정정 ~10만→9,054 ②icloud_new ~75%의 D12·D16 경계조건 ③실 near-dup율(919쌍)→D8 재검토. ③ 참고 실측(④ dedup, 2026-06-10): 파일명 overlap 427 중 **바이트 동일은 165뿐** — 재인코딩 사본이 near-dup 영역에 남아 있어 D8 결정의 실효 범위 큼. → [§7.8](docs/01_eda_findings.md)

## 🧹 코드 품질 후속 (낮음)
> 2026-06-15 세션 완료 → ARCHIVE: CLI golden 테스트·모델명 상수화·index_errors 정리·caption N+1·prune 파이프라인 자동호출·ruff format 부채. 잔여 backlog:
- [ ] **(backlog) 미커버 CLI 커맨드** — `db load-sources`·`photos export`·`search semantic`·`serve-api` 단위테스트 없음(나머지 리프 커맨드는 커버됨).

## 📌 사용법
- 세션 시작 시 이 파일을 먼저 읽어 현재 위치 파악.
- **완료 항목은 체크만 하지 말고 즉시 [`TODO_ARCHIVE.md`](TODO_ARCHIVE.md)로 이관** — 완료 날짜·시각(분단위) + commit hash 기재. 규약: [`AGENTS.md` §7 ARCHIVE](AGENTS.md).
- 설계가 바뀌면 코드·이 파일보다 **SoT 문서(PLAN.md·docs/adr/)를 먼저** 갱신(불변 규칙).

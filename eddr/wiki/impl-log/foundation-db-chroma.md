---
title: "Foundation DB + Chroma 구현"
source: ["docs/FOUNDATION_DB_USAGE.md", "docs/adr/0006-vector-store-selection.md"]
last_verified: 2026-06-10
status: fresh
confidence: high
tags: [impl-log, sqlite, chroma, vision, cli]
---

# Foundation DB + Chroma 구현

## 요약

2026-06-10 기초 DB 구축 단계는 SQLite ledger + Chroma sidecar로 구현했다.
SQLite는 `photos`, `captions`, `embeddings`, `index_errors`, status checkpoint를
소유하고 Chroma는 `eddr_caption_text_v1` caption-text vector 검색을 소유한다.

## 구현된 기능

- `eddr db init`: SQLite ledger schema 생성.
- `eddr db load-sources`: EDA cache, Google Takeout manifest, Photos export dir
  source record 적재.
- `eddr photos export`: `osxphotos export` wrapper. `--download-missing`,
  `--use-photokit`, `--update`, `--skip-movies`, `--not-hidden` 사용.
- `eddr vision run`: local Ollama caption + caption-text embedding + Chroma
  upsert batch.
- `eddr search semantic`: query embedding 후 Chroma semantic search 실행.

## 현재 상태

2026-06-10 실측 (검증 패턴: `notebooks/05_index_verification.ipynb`):

- SQLite `photos`: 11,689 rows.
- Status counts: `caption_done=9383`, `skipped_video=2306` (영상은 의도 제외).
- SQLite `captions`: 9,383 rows (영어·P3_hybrid).
- SQLite `embeddings`: 9,383 `caption_text` rows (`qwen3-embedding:8b`).
- Chroma `eddr_caption_text_v1`: 9,383 vectors — SQLite↔Chroma 3-레이어 정합 PASS.
- 한국어 시맨틱 검색 검증: 바다·음식·야경 5/5 관련 (D19 확증).

2026-06-10 검증 노트북 05 전면 강화 재실행 — **12게이트 전원 PASS** (당일
taken_at CHECK 1건 발견→해소 이력 포함, 아래 §C-2 항목):

- 신규 게이트: §B-5 캡션 본문 전수 일치(Chroma documents == captions.text,
  9,383/9,383), §C-1 이미지 파일 실존 전수(9,383/9,383), §D-3 self-retrieval
  라운드트립(top-1 98%·top-5 100%, 자기 거리 median 0.0000),
  §C-3 `Search keywords:` 커버리지 100%(bold 4,370 + plain 5,013).
- 육안 증거: §C-4 4계층 레코드 추적(사진 포함)·§C-5 무작위 9장 사진↔캡션
  그리드·§D-2 한국어 5쿼리 top-5 실사진 그리드. 사진 표출 출력은
  notebooks gitignore 전제(ADR-0001은 외부 LLM 전송 경계라 로컬 표시 무관).
- 실측 발견 2건(TODO 등록): ① image_path 표기 혼재 — google_takeout
  1,385건만 상대경로(파일은 전부 실존, CWD 의존 위험) ② L2 거리 절대값은
  관련도 컷오프 불가(음성 '북극 오로라' 0.664 < 긍정 '도시 야경' 0.708) —
  ⑦은 rank 기반으로 설계.
- §E-2 라이브 재검증: `0beb879`·`2a52ad3` 해소 3건(skipped_video enum·
  L2 명시·docstring) 문서 원문 존재 확인 — 매 실행 시 회귀 감시.
- §D-5 실사용 질의 평가(같은 날 추가): 골든셋 후보 풀 문장형 7질의,
  GT = local 여행 폴더명·taken_at 연도 proxy(NFC 정규화 비교). hit@10 —
  여행 고유 장면(아이슬란드 오로라) 7/10(2025년 2차 아이슬란드까지 치면 사실상
  10/10), 지명(제주) **0/10**·(일산) 2/10, 연도(2013) 4/10. 지명·시간 축은
  캡션에 없어 캡션 단독 불가를 실측 확증 → ⑦ semantic+메타(trip·geocode·날짜)
  합성 근거. cross-source 중복(이탈리아 overlap 357)이 폴더 GT를 과소집계
  → ④ dedup 후 GT 정밀화 가능.
- §D-5 육안 판정(같은 날, 사용자 직접): 이탈리아 top-5 **실질 5/5**(✗는
  iCloud 사본 — ④ dedup 근거 육안 확정), 제주 top-5 중 2건 실제 제주(폴더
  proxy 0/10의 블라인드스팟 실증), 일산 top-5 중 3건 적중, 몽골 top-5에
  국내 2·이탈리아 1, 결혼 top-5에 GPS 무 이탈리아 1 혼입, 2013년 질의에
  타 연도 혼입. 아이슬란드는 보유 오로라 전량이 아이슬란드産이라 지명
  변별력 측정 불가. → ⑦ 설계 입력(사용자 제안): 장소 질의 응답에서 GPS 무
  사진 제거/하단 정렬 또는 GPS 유무 응답 구획(TODO ⑦ 등록).
- 데이터 품질 CHECK 신설(§C-2): local taken_at 806건이 EXIF 콜론 포맷
  (`2018:04:10 18:38:51`)으로 SQLite 날짜 파싱 불가 — **해소(같은 날,
  `c4b2199`)**: `_iso_or_none`에 EXIF→ISO 정규화 추가(무효값은 None) +
  `load-sources` 재적재로 806→0, 상태·captions·embeddings 9,383 보존,
  local 연도 축(2015~2025) 복원. 재실행 검증 **12게이트 전원 PASS(ALL
  PASS)**. §C-2는 상시 게이트로 유지(향후 회귀 감시).

## 완료와 미완료 구분

완료:

- Chroma/FAISS 평가 및 Chroma 채택 결정.
- SQLite ledger schema와 source loader.
- Chroma persistent store adapter.
- Photos export wrapper.
- Ollama Vision batch.
- Semantic search CLI.
- 전체 Photos/iCloud asset materialization (`photos export`).
- 전체 Vision caption/vector batch — dual-server LAN 분산, 9,383장 (ADR-0007).
- 캡션 벡터 검색 품질 검증 — 한국어 시맨틱 검색 5/5 (notebooks/05).
- load-sources 안전 수정 2건 — D18 영상 필터를 3경로 공통 적용(vision_manifest·
  takeout·photos export stem 매핑, Live Photo `.mov` 오염 방어) + `upsert_photo`
  ON CONFLICT `indexing_status` CASE WHEN 보존(vision 이후 단계는 보존, 적재
  단계는 갱신). 2026-06-10, commit `b5e230d` — 회귀 테스트 9건·suite 57 passed.
- taken_at EXIF 콜론 포맷 정규화 — `_iso_or_none` EXIF→ISO 변환 + 재적재로
  local 806건 교정(상세 위 §C-2 해소 항목). 2026-06-10, commit `c4b2199` —
  테스트 5케이스 추가·suite 63 passed.

미완료:

- 없음 — 이 단계 범위는 전부 완료.

## 남은 작업

없음. 2026-06-07판 "다음 운영 순서" 4단계는 2026-06-08 전량 실행 완료(실측은 위
"현재 상태"), load-sources 안전 수정 2건은 2026-06-10 완료(`b5e230d`) —
**`eddr db load-sources` 재실행 금지 제약 해제**(재실행해도 caption_done·
skipped_video 상태와 captions 9,383건 보존). 후속 단계(④ dedup·geocode·
Daily Radius)는 [`TODO.md`](../../TODO.md).

자세한 사용법과 검증 명령은 `docs/FOUNDATION_DB_USAGE.md`를 따른다.

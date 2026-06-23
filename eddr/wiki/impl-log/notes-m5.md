---
title: "D26 M5 — 사진 메모 + 검색 합류"
source: ["docs/prd.md", "docs/scenario.md", "docs/adr/0009-map-local-search.md"]
last_verified: 2026-06-12
status: fresh
confidence: high
tags: [impl-log, notes, embedding, rrf, web]
---

# D26 M5 — 사진 메모 + 검색 합류 (2026-06-12)

S5(라이트박스 메모 → 임베딩 → 검색 반영) 구현 — D26 마지막 구현 마일스톤. commits `62425ba`(API·note leg)·`97eed12`(NoteEditor)·`09b436c`(리뷰 수정 4건).

## 서버 (`62425ba`)

- `notes` 테이블(photo_id PK·CASCADE — 사진별 1메모) + CRUD. `PUT /api/photos/{id}/note`(404/422/**2,000자 캡**) — upsert 후 **동기 임베딩**(qwen3-embedding 무지시 raw → Chroma **`eddr_note_text_v1` 별도 컬렉션**, `embeddings` kind='note_text'). 임베딩 실패 시 저장은 성공 + `embedded:false`(embeddings 행 부재 = 재임베딩 식별 계약, index_errors stage=note_embed). `DELETE` — 벡터→notes→embeddings 순(크래시 시 메모 잔존=재시도 가능, 고아 없음). duplicate는 canonical 귀속(ADR-0002). detail 응답에 note
- deps `NOTE_COLLECTION` 단일점 — 라우트·QueryService·golden 러너 동형 주입

## 검색 융합 — 거리 경쟁 정규화 (스펙 편차, 리뷰 승인)

naive 설계(note leg rank 1 단순 RRF 합류)는 **실측 게이트 실패**: 메모가 전 캡션 9,383장보다 질의에 가까워도(거리 1위) 1-item leg의 1/61 단독 점수가 vector+lexical 이중 출현 후보 63개에 밀려 64위(k=50 절단 밖). 보정 — 캡션·메모가 **같은 임베딩 공간**(둘 다 qwen3 무지시 raw, 동일 L2)임을 이용해 메모 거리를 캡션 풀 거리 경쟁(가상 순위)으로 정규화(`_fold_note_hits`):

- 풀 안에 들면 vector leg 병합 + note leg 이중 출현(합의 후보), 탈락(전 캡션보다 먼 거리)이면 기여 0 — 무관 질의 비오염. **절대 거리 컷오프·튜닝 상수 없음**(질의-적응적 상대 경쟁 — 노트북 05 §D-4 준수)
- 리뷰 보정 3건(`09b436c`): ① 자기 캡션이 더 가까우면 강등 금지(min 승격) ② 채택 거리를 경쟁 풀에 삽입(후속 메모 과승격·동률 사전순 결정 방지) ③ **입장 판정은 원본 캡션 풀·순위 삽입은 갱신 풀로 분리**(캡션 有 시 동치 — 채택 거리 ≤ 원본 최대; 캡션 0이면 전원 채택)
- `_rrf_fuse(*ranked_lists)` 가변 인자 일반화·빈 컬렉션이면 leg 생략(query 0회 — 메모 0건 오버헤드 0·기존 경로 바이트 동일)

## 웹 (`97eed12`)

NoteEditor(라이트박스 하단 — 메모 보기(탭=편집)↔textarea(maxLength 2,000)+저장/삭제, embedded:false 시 "ollama 실행 후 다시 저장" 안내)·`:has` 셀렉터로 입력 중 이미지 축소(iOS 키보드)·Lightbox 키 가드가 TEXTAREA 타깃 차단(IME 안전)·`.note-view` max-height 30vh.

## 실DB E2E (가역 — 흔적 0 원복)

캡션이 '민들레'인 개심사 사진에 "서산 개심사 벚꽃 나들이 테스트" 메모 → **"개심사 벚꽃" rank 1 합류**(베이스라인 미포함 → 인과 입증) · 무관 질의("몽골 은하수" 등) **top5 lane 바이트 불변** · "겹벚꽃" 준-관련 질의엔 정당 합류(메모 '벚꽃' 의미 연관) · DELETE 후 재검색 미포함 + notes/embeddings/Chroma/index_errors **흔적 0**.

## 리뷰 (통합 1회)

스펙 전 항목 ✅ + **편차 정당 판정**(D-4 비위반·동일 공간 성립·단조성·과설계 아님 — 4축 검증). 품질 4건 수정(`09b436c`). 관찰: 동시 PUT 두 탭 텍스트-벡터 어긋남 가능(자가복구·저위험), 임베딩 모델 교체 시 구모델 note 벡터 잔존 — 백로그.

## 수치·잔여

pytest **271 passed** · Playwright 모바일(메모 작성→토스트→재진입 표시→삭제) PASS. 백로그: embedded:false 일괄 재임베딩 배치, 모델 교체 시 note 재임베딩. 골든 10/10 실채점은 사용자 match 작성 후(메모 0 상태에선 기존 경로와 동일 — 구조적 무회귀).

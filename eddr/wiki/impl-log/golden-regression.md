---
title: "⑧ 골든셋 회귀 — 러너 + 1차 ollama 결과 + think A/B"
source: ["docs/golden_set.yaml", "docs/PLAN.md#10", "docs/GOLDEN_QUERY_CANDIDATES.md"]
last_verified: 2026-06-11
status: fresh
confidence: high
tags: [golden-set, regression, ollama, thinking, query]
---

# ⑧ 골든셋 회귀 (2026-06-11)

골든셋 10문항이 사용자 선별로 확정 단계에 들어갔고(`docs/golden_set.yaml`,
`confirmed: pending`), 회귀 러너(`eddr golden`)로 1차 ollama 무비용 실행 2회
(think on/off)를 완주했다. 커밋 `1396bde`(골든셋+러너) · `6e3fb00`(경로 픽스+
`--think`) · `d1d224d`(G04 수정). 테스트 174→**178 passed**.

## 골든셋 v1 (사용자 선별 2026-06-11)

- 후보 풀 Q001~Q050 중 **Q1·4·5·9·10·25·31** + 사용자 신규 3문항(이탈리아 시기·
  용산 음식·은하수) = 10문항(G01~G10).
- 분포 **R1 2 / R3 7 / 복합 1 — R2 0문항**: ADR-0004 person 질의 폐기와 정합,
  기존 "R1 5/R2 3/R3 2" 분포 계획을 사용자 선별로 대체(R2 재정의 항목 해소).
- 문항별 expect/reference는 실DB ground truth로 작성(부산 trip 2개·운여해변
  distractor·은하수 34/36 GPS 무·개심사 GPS 0 등). **confirmed는 사용자 확정 대기.**

## 러너 (`src/eddr/query/golden.py` + `eddr golden`)

- 문항마다 **fresh ChatEngine**(독립 대화) 실행, JSONL **증분 flush**(중단 내성) +
  사람 채점용 md 리포트(답변·tool 호출·기대 기준·빈 판정 칸).
- `auto_check`는 보조 신호만(ok/warn/manual): 사진 0장·핵심 문자열 누락 감지.
  통과 판정 아님 — **최종 채점은 사람**(Done = 8/10).
- `--backend {claude,ollama}` · `--think/--no-think`(ollama 전용, 기본=모델 기본값).
- 함정: 모델명 `.`(qwen3.6) 때문에 `with_suffix`가 확장자 오인 → 경로 문자열 직접 조립.

## 1차 결과 (qwen3.6:27b, `reports/golden/20260611_*`)

| run | 총시간 | 오류 | 잠정(사전 평가) |
|---|---|---|---|
| think on (기준선) | 36분 (60~681s/문항) | 0 | 강통과 7 · 경계 3(G02·G04·G10) · 육안 1(G06) |
| think off | **13분** (40~128s/문항) | 0 | 7문항 동등 이상(G02·G03·G10은 우세) · G06 포기 · G09 1장 |

- **think A/B 결론**: ollama 레그(배관 검증·반복 회귀)는 `--no-think` 권장 —
  2.8배 빠르고 대부분 동등 이상. thinking이 가른 곳은 **G06**(고난도 탐색: on은
  3-tool 우회로 후보 발견, off는 즉시 포기)과 **G09**(끈기: on 5장 vs off 1장).
  본선 Claude는 adaptive 유지(프로덕션 serve와 동일 구성이어야 채점이 유효).
- no-think 부작용 관찰: 답변에 한자 혼입(锡箔지·2회分の) — 채점엔 영향 없는 수준.
- 거짓 양성 방지 사례: G03 두 run 모두 몽골 필터로 운여해변 distractor 회피 성공.

## 회귀가 잡은 결함과 수정

- **G04(부산 1박2일) 양 run 공통 실패 → 수정·검증 완료(`d1d224d`)**: 원인은 기능이
  아니라 tool description — `list_trips.countries`가 trip 이름 LIKE로 '부산'을 이미
  매칭하는데 설명이 "국가명"뿐이라 모델이 못 썼고(존재하지 않는 `cities` 인자 시도
  → is_error 복구 동작은 실증됨), '대한민국' 조회는 최신순 10개 잘림으로 2018-12
  trip 탈락. 설명에 지역명 매칭·잘림 주의 명시 → 단일 문항 재검증에서
  `list_trips(['부산'])` 호출·두 trip(2018-12·2025-04) 정답(48.5s).
- **G02 recall 낮음**(on 2장/off 4장, 참고 모집단 130장): k×5 over-fetch 후 국가
  필터 통과분이 적음 — 본선(Claude)에서 재관찰 후 OVERFETCH_FACTOR/재시도 판단.
- **G10 위치구분 미언급**: has_location=false 구분 멘션(시스템 프롬프트 지시)을 양
  run 모두 생략 — qwen 한계인지 프롬프트 문제인지 본선에서 판별.

## 다음

1. (사용자) 1차 리포트 채점(모바일 전송됨) + `golden_set.yaml` confirmed 확정.
2. ⑧ 2차: `ANTHROPIC_API_KEY` 설정 후 `eddr golden --backend claude` 최종 채점.
   반복 회귀는 `eddr golden --backend ollama --no-think`(13분).

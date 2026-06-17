# 포스트모템 — 냉면·음식 키워드 캡션 품질 (2026-06-14)

> blameless 회고. 객관적·학습 중심. 본 문서는 **문제의 발견·분석·해결(메인 작업)**을
> 다루며, 해법을 production에 적용하며 만난 인프라 이슈는
> [`2026-06-14-caption-recaption.md`](./2026-06-14-caption-recaption.md)에서 다룬다.

## 1. 개요

골든셋 평가 중 **"냉면" 검색에 콩나물·숙주 사진이 상위 노출**되는 오염을 발견했다.
원인을 "검색 파라미터 문제"로 단정하지 않고, **캡션 오인(생성)과 검색 증폭(retrieval)을
분리**하는 audit 경로를 먼저 만들어 진단했다. 결과는 검색 로직이 아니라 **production
기본 비전 모델(`gemma4:e2b`)이 콩나물을 `noodles`로 오캡션**하고, 그 텍스트가 검색에
충실히 증폭된 구조였다. 이어 26장 절대품질 평가로 **"프롬프트가 아니라 모델 체급"**이
근본 원인임을 입증하고, grounding 프롬프트(`p5_grounded`) + 큰 모델로 음식을 재캡션해
오염을 해소했다.

## 2. 타임라인

- **발견** — "냉면" 검색 top-3에 콩나물 2건. `eddr search audit`으로 provenance 기록.
- **진단(분리)** — keyword DF 분석: `cold noodles` DF 0, `naengmyeon` DF 1, **`food` DF 1,066**,
  `bean sprouts` DF 6. → sprout recall 부족이 아니라 **캡션 vocabulary 빈약 + `food` 같은
  broad keyword 오염 + 콩나물→noodle 오캡션**이 결합된 문제로 규명.
- **1차 가설(프롬프트)** — 음식 특화 `p3_hybrid_food_guard` 프롬프트 추가. 미니 A/B(2장):
  `gemma4:e2b`는 food_guard로도 `noodles` 잔존, `qwen3-vl:8b`는 제거. → "모델이 변수"라는 신호.
- **검증(절대품질 평가)** — 범용 26장(음식·인물·풍경·문서·상점) Opus 직접 채점. `gemma4:e2b`
  7.1/치명결함 4 vs `qwen3-vl:8b` 9.38·`gemma4:31b` 9.50/치명결함 0. **프롬프트 가설 기각,
  모델 체급 가설 입증.** `p4`·`p5_grounded`(범용 grounding) 도출.
- **해결(재캡션)** — 음식 1,393장을 큰 모델(`gemma4:31b`·`qwen3-vl:8b`)/`p5_grounded`로 재캡션.
  콩나물 케이스가 "noodles"→**"bean sprouts/rice"**로 정정, 냉면 검색 top-10에서 콩나물 제거 확인.

## 3. 근본 원인 분석

표면 증상("냉면 검색에 콩나물")의 실제 원인은 3층이었다.

1. **캡션 오인(생성)** — `gemma4:e2b`가 얇고 흰 재료(콩나물·숙주·무채)를 `noodles`/`vermicelli`로
   오인. 모델 용량 한계로, 음식 식별 지시(food_guard)를 줘도 교정되지 않음.
2. **검색 증폭(retrieval)** — 오캡션 텍스트가 ① `qwen3-embedding`으로 "noodle 근방" 벡터가 되어
   Chroma 상위 진입, ② FTS5에서 `noodle` 어간 매칭, ③ RRF에서 vector·lexical 양쪽 등장해 이중
   합산. + `food`(DF 1,066) 같은 broad keyword가 모집단을 넓게 오염.
3. **프롬프트 교정의 한계** — 작은 모델은 grounding 지시를 수행할 용량이 부족(평가에서
   A/S센터 화면을 "식당 메뉴"로 환각하는 등 역효과까지 관측).

## 4. 영향 범위

- **검색 정확도(단일 사용자)** — 음식 질의("냉면" 등)에 무관한 콩나물·broad food가 섞여 신뢰 저하.
- **범위의 일반성** — 평가 결과 음식뿐 아니라 인물(성별·인원 오류), 문서(OCR·"식당메뉴" 환각),
  메타맥락(화면캡처·거꾸로 사진 미인식)에서도 `gemma4:e2b`가 약함이 드러남 — 즉 음식은 빙산의 일각.

## 5. 대응 및 해결

- **audit으로 원인 분리** — 검색 튜닝(reranker·가중치)에 손대기 전, 캡션 오인 vs 검색 증폭을
  비변경 audit으로 분리해 "캡션이 근원"임을 데이터로 확정.
- **절대품질 평가로 모델 규명** — 키워드 pass/fail(대리지표)이 아니라 Opus가 사진을 직접 대조한
  5차원 rubric(정확·충실·환각·구체·형식)으로 "모델 체급" 입증.
- **grounding 프롬프트 + 모델 교체** — `p5_grounded`(보이는 것만, 모호하면 일반어, 매체맥락 명시)
  + `gemma4:31b`/`qwen3-vl:8b`로 음식 재캡션. 캡션·Chroma 분리로 안정 적용(상세는 연계 포스트모템).

## 6. 재발 방지

1. **캡션 품질 평가 인프라 상설화** — `eddr search audit`(provenance), `prompt-ab-eval`(게이트),
   절대품질 rubric. 검색 이상 시 "캡션 vs 검색"을 먼저 분리 진단.
2. **모델 선택 기준** — 음식·메타맥락은 `gemma4:31b`, 텍스트/OCR/문서는 `qwen3-vl:8b`. 비전
   캡션에 소형 모델(`gemma4:e2b`) 단독 의존 지양.
3. **grounding 프롬프트 기본화 검토** — `p5_grounded`를 큰 모델과 함께 사용.
4. **broad keyword 관리** — `food`처럼 DF가 비대한 keyword의 검색 가중 재검토(후속 과제).

## 7. 교훈 (배운 점)

- **대리지표 vs 절대품질** — "noodle keyword가 있나"가 아니라 "캡션이 사진을 맞게 기술하나"를
  봐야 했다. 키워드 게이트는 면/콩나물에만 작동하지만 절대품질은 전 도메인에 일반화된다.
- **모델 체급 > 프롬프트** — 작은 모델은 프롬프트로 한계를 못 넘는다(오히려 환각 유발). 프롬프트
  튜닝에 매달리기 전 모델 용량을 의심.
- **원인 분리 우선** — 검색 이상을 "검색 파라미터"로 성급히 단정하지 않고 audit으로 생성/검색을
  분리한 것이 정확한 해법(재캡션)으로 이어졌다.
- **증상은 빙산의 일각** — "냉면→콩나물" 하나를 파다가 인물·문서·메타맥락 전반의 캡션 품질
  문제를 발견. 좁은 버그가 시스템적 한계를 드러내는 신호일 수 있다.

## 부록

- 관련 코드(master): `eddr search audit`, `prompt-ab-eval`, `p4`/`p5_grounded` 프롬프트.
- 산출물: `reports/caption_audit/20260613_quality_report.md`(평가 점수표),
  `wiki/impl-log/caption-quality-audit.md`.
- 연계 포스트모템: [`2026-06-14-caption-recaption.md`](./2026-06-14-caption-recaption.md)
  (재캡션 실행·ChromaDB 데드락·mlx 환각).
- 후속 과제: 메뉴·포스터 등 "텍스트 속 음식명" false positive 검색 정책, `food` broad keyword 가중.

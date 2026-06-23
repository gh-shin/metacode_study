---
title: "캡션 품질 감사 — strand food 오인 분리"
source: ["docs/superpowers/plans/2026-06-13-caption-quality-audit.md", "reports/caption_audit/20260613_naengmyeon_labeled.json", "reports/caption_audit/20260613_prompt_ab_qwen_food_guard.jsonl", "reports/caption_audit/20260614_prompt_ab_eval_qwen_food_guard_7partial.json"]
last_verified: 2026-06-14
status: fresh
confidence: high
tags: [caption, vision, retrieval, audit, food]
---

# 캡션 품질 감사 (2026-06-13)

냉면 검색에 콩나물/숙주류 음식이 섞이는 현상을 계기로, 검색 튜닝 전에
**캡션 오인과 검색 증폭을 분리**하는 감사 경로를 추가했다. 결론은 벡터 자체의
단독 문제라기보다, caption text가 `noodles/vermicelli/food`로 잘못 저장되고
검색이 그 텍스트를 충실히 끌어온 구조다.

## 구현

- `eddr search audit` — query, keyword DF, top-k hit의 vector rank/distance,
  lexical rank, RRF 기여, matched keywords, caption keywords, manual bucket을 JSON으로 기록.
- `reports/caption_audit/20260613_food_strand_labels.json` — 수동 라벨 초안:
  `wrong_object_sprouts_as_noodles`, `shredded_daikon_as_noodles`,
  `product_text_false_positive`, `exact_dish_missing` 등.
- `p3_hybrid_food_guard` — food-specific prompt variant. 기본 production prompt는 변경하지 않음.
- `vision prompt-ab` 확장 — `--caption-model`, 반복 `--prompt`, 반복 `--photo-id`로
  문제 사진을 직접 재캡션 비교 가능.

## 실측

- 냉면 audit: `cold noodles` caption DF 0, `naengmyeon` DF 1, `food` DF 1066.
  top-3 중 2건은 `wrong_object_sprouts_as_noodles`, 1건은 poster/text false positive.
- 콩나물/숙주 audit: `bean sprouts` DF 6, `mung bean sprouts` DF 0, `food` DF 1066.
  sprout recall 자체보다 캡션 vocabulary 빈약과 `food` broad keyword가 더 큰 오염원.
- Prompt/model mini A/B(2 JPG):
  - `gemma4:e2b + p3_hybrid_food_guard`: 콩나물을 sprouts로 잡기 시작하지만 keyword에
    `light noodles`를 남김.
  - `qwen3-vl:8b + p3_hybrid_food_guard`: 콩나물 케이스에서 noodles를 제거하고
    `bean sprouts`, `rice`, `green onions`로 더 정확히 기술. 더 느림.
- qwen food_guard 부분셋 재평가(7 JPG, 2026-06-14): format/privacy 7/7,
  real noodle recall 3/3. 단 `text_poster_only` 1건이 포스터 속 냉면/국수 텍스트와
  일러스트를 `noodle/noodles` keyword로 남겨 false-forbidden gate는 실패
  (`false_forbidden_rate=0.25`). 이는 콩나물 오인과 별개로, "사진 속 실물 음식"과
  "포스터/문서에 적힌 음식"을 검색 타깃에서 어떻게 구분할지 정책 결정이 필요하다.

## 다음 의사결정

1. 30-50장 food-strand 감사셋을 확정하고 `visual_target/caption_claims_target`
   라벨을 보강한다.
2. `qwen3-vl:8b + p5_grounded` 또는 `gemma4:31b + p5_grounded`를 감사셋에
   재실행해 콩나물/숙주류 false noodle keyword 0, real noodle recall >=90%,
   format/privacy 100%를 확인한다. 포스터/문서 속 음식명은 별도 bucket 또는
   검색 정책으로 분리한다.
3. 통과 시 bulk re-caption 후보로 검토한다. 실패 시 search ranking 튜닝보다
   비전 모델 교체 또는 image-aware rerank를 우선 검토한다.

## 범용 품질 평가 (2026-06-13 오후)

audit 인프라 위에서 범용 26장(food·people·landscape·document·store_product 5유형
층화, 콩나물·떡 오캡션 회귀 3장 포함)으로 모델×프롬프트 캡션 **절대 품질**을
Opus가 사진 직접 대조 rubric(5차원 0–10 + 치명결함) 채점.

- 1차 4셀 평균/치명결함: `gemma4:e2b`/p3 7.12/4 · `gemma4:e2b`/p4 7.08/3 ·
  `qwen3-vl:8b`/p3 9.38/0 · `gemma4:31b`/p4 9.50/0.
- **결론: 냉면→콩나물 오분류의 근본 해결은 모델 교체.** `gemma4:e2b`는 프롬프트
  (food_guard·p4_grounded)로도 콩나물/떡을 noodle로 부르는 치명 오분류를 못 고침
  (grounding 지시 수행 용량 부족, 오히려 A/S센터→"식당메뉴" 환각 유발). 큰 모델은
  프롬프트 무관 정확. **"프롬프트 변경" 가설 기각, "모델 체급" 가설 입증.**
- 신규 프롬프트 `p4_grounded`(0ced224)·`p5_grounded`(061e94b) 추가 — 범용 grounding,
  production 기본 미변경. 2차 p5: 큰 모델에서 과소특정(salmon/pork/soju 명명)·
  메타맥락(화면촬영/거꾸로) 개선, 치명결함 0·콩나물 회귀 없음.
- 도메인별 강점: 텍스트 OCR/문서 `qwen3-vl:8b`, 음식·메타맥락 `gemma4:31b`.
- 권고 프롬프트 `p5_grounded`. 모델 채택·재캡션은 **다음 스텝(미결정)**.
  재캡션 비용 실측(단일 호스트, 9,383장): e2b ~18h · qwen8b ~80h · gemma31b ~130h.
- 상세·점수표: `reports/caption_audit/20260613_quality_report.md`,
  `..._quality_scores.json`, `..._quality_p5_compare.json`.

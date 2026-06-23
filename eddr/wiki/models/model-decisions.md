---
title: "모델 선택 결정 추적"
source: ["docs/SOLUTION_REVIEW.md", "docs/PLAN.md#7"]
last_verified: 2026-06-07
status: fresh
confidence: medium
tags: [models, vision, embedding, pending]
---

# 모델 선택 결정 추적

> **A/B 테스트는 Vision 단계(빌드순서 ⑤)에서 골든셋으로 결정 — 인덱싱 적재는 완료됐으나 골든셋 미작성이라 모델 A/B 실측은 보류.**
> 아래 모든 권고는 `docs/SOLUTION_REVIEW.md`(불변 Source)에서 컴파일된 것이며, 수락/거부는 골든셋 A/B 측정 완료 전까지 결정하지 않는다.

## 권고 현황 추적표

| 영역 | 현행 (PLAN §7) | 권고 (SOLUTION_REVIEW) | 우선순위 | status |
|------|---------------|----------------------|---------|--------|
| 캡션 | gemma4:e2b (현행 적재) | Qwen3-VL 8B (경쟁후보: Gemma 4 26B MoE) | P1 | **P3_hybrid 확정**·D19 PASS (03) · 모델 A/B는 ⑤ · day-place 보강(04) v1 보류—환각 발목 |
| 텍스트 임베딩 | qwen3-embedding:8b (현행 적재) | Qwen3-Embedding-8B (MTEB-multi 70.58 vs BGE-M3 63.0, +7.6p) | P1 | **accepted for caption_text bulk** |
| 이미지 임베딩 | 3모델/2벡터 설계(SigLIP/CLIP 미정, D20) | Qwen3-VL-Embedding 8B 통합 (MMEB-V2 77.8 SoTA, fallback: SigLIP 2 So400m / Jina-CLIP v2) | P2 | pending |
| 튜닝 | dHash cutoff=1, KDE(Daily Radius), 규모 ~10만 | dHash cutoff 인덱싱 후 분포로 재튜닝 · HDBSCAN(Daily Radius) · 규모 ~10만→실측 9,047로 갱신 | P3 | pending |

## 각 영역 상세

### P1-캡션: Qwen2.5-VL 7B → Qwen3-VL 8B
- SOLUTION_REVIEW 판정: 🔴 UPGRADE
- 근거: Qwen3-VL(arXiv:2511.21631, 2025-11)은 동급 7~8B에서 추론 우위, 속도 15–60% 빠름, OCR 지원 32개 언어(이전 19개). Ollama(`qwen3-vl:8b`)로 로컬 실행 가능 — D3(전부 로컬, M4 Pro 64GB)와 정합.
- 경쟁후보: Gemma 4 26B MoE(2026-04-02, 550M vision encoder, MoE라 추론비용≈4B급, Q4로 ~16GB). 최종 선택은 골든셋 A/B로 결정.
- **03 EDA(2026-06-04)**: gemma4 e2b로 캡션 프롬프트 3종 비교 → **P3_hybrid(서술+키워드) 채택**, **D19 PASS**(한국어질의 recall@10 0.70, P3 0.70 > P2 0.60). 26b가 정확하나 2.2배 느림. 모델 A/B(Qwen3-VL vs gemma)는 ⑤ 골든셋. → `docs/01_eda_findings.md §8`
- status: 프롬프트 **P3_hybrid 사용자 확정**(2026-06-04) · 모델 A/B(Qwen3-VL vs gemma)는 ⑤ pending

### P1-텍스트 임베딩: BGE-M3 → Qwen3-Embedding-8B
- SOLUTION_REVIEW 판정: 🔴 UPGRADE
- 근거: Qwen3-Embedding(arXiv:2506.05176) MTEB multilingual No.1(70.58), BGE-M3(63.0) 대비 +7.6p. 100+ 언어(한국어 포함), MRL 가변 차원, Ollama 제공.
- 주의: 한국어 단독 벤치마크 미확인 → 골든셋 R2/R3으로 A/B 실측 필요.
- status: **pending**

### P2-이미지 임베딩: 3모델/2벡터 → Qwen3-VL-Embedding 8B 통합
- SOLUTION_REVIEW 판정: 🔴 REDESIGN
- 근거: Qwen3-VL-Embedding(arXiv:2601.04720, 2026-01)이 텍스트+이미지를 단일 표현 공간으로 통합. MMEB-V2 77.8(SoTA, 직전 대비 +6.7%). D20의 "3모델/사진당 2벡터" 구조를 단순화 가능.
- 대안: SigLIP 2 So400m(arXiv:2502.14786, 109개 언어) 또는 Jina-CLIP v2(arXiv:2412.08802, 89개 언어)로 image leg만 채우는 방식도 PLAN 의도 충족.
- status: **pending**

### P3-튜닝 (인덱싱 후 데이터 기반)
- dHash cutoff=1: EDA에서 93쌍 전부 Hamming 0(export artifact). cutoff가 과타이트할 가능성 → 인덱싱 후 전수 분포로 재설정.
- Daily Radius: KDE→격자 양자화(EDA에서 이미 교체)는 타당하나, HDBSCAN(haversine)이 경계 문제 없이 더 견고.
- 규모: PLAN "~10만 장" → EDA 실측 9,047장. 배치 설계 전제에 반영 권장.
- status: **pending**

---

이 page가 SOLUTION_REVIEW 권고의 수락/거부 status를 추적한다(원본 SOLUTION_REVIEW.md는 불변 Source).

# Day-level 장소추정 캡션 보강 EDA — 설계 스펙

- **날짜**: 2026-06-04
- **상태**: approved (brainstorming) → 구현 계획 대기
- **산출물**: `notebooks/04_day_geocaption_eda.ipynb`
- **관련 문서**: `docs/PLAN.md`(D19/D20·§7), `docs/01_eda_findings.md`(§8.6 지명약점·§7 핸드오프), `wiki/models/model-decisions.md`, `docs/adr/0003-llm-tool-surface.md`, `docs/adr/0001-privacy-boundary.md`
- **선행 EDA**: `notebooks/01_eda.ipynb`(메타 가정), `notebooks/02_full_dataset_eda.ipynb`(정합성·비전 근거데이터), `notebooks/03_vision_caption_eda.ipynb`(캡션 프롬프트·D19 PASS)

---

## 1. 목적 & 배경

03이 **캡션검색의 "지명 약점"**을 드러냈다(findings §8.6): 캡션검색은 *"무엇이 찍혔나"*(결혼식·아이슬란드·이탈리아 = recall@10 1.00)엔 강하지만 *"어디서"*인 **고유지명(제주도·일산호수공원 = 0.00)**엔 약하다. e2b 영어 캡션이 `Jeju`·`Ilsan`을 글자로 담지 못해, 시각적으로 평범한 지명 질의가 디스트랙터와 갈리지 않는다.

이 약점의 보완 경로는 둘이다 — ① **시각 임베딩**(image leg, D20: SigLIP/CLIP/Qwen3-VL-Embedding) ② **캡션 지능화**(더 큰 모델이 지명을 텍스트로 주입). 본 세션은 **사용자 결정으로 ②(캡션 경로)를 먼저** 다룬다. ①(image leg)은 별도 세션으로 미룬다.

**핵심 가설**: `gemma4:26b`의 세계 지리 사전지식 + **동일 묶음 multi-image** 단서를 결합하면, GPS가 없어도 **coarse 지명**(예 `Jeju Island`)을 추정해 캡션에 주입할 수 있고, 이로써 03에서 0.00이던 지명 질의 recall이 오른다. 캡션에 `Jeju`가 텍스트로 들어가면 03에서 이미 검증된 multilingual 임베딩(`qwen3-embedding:8b`)이 한국어 "제주" 질의와 곧바로 매칭된다 — **새 임베딩 모델 불필요**.

EDA는 구현 게이트가 아니라 insight 확보다(01–03 계승). 결과가 약해도 빌드를 막지 않으며, D19 캡션 보강·모델 선택의 근거 데이터를 남긴다.

## 2. 입력 데이터 (03 핸드오프 재사용)

| 자산 | 규모 | 비고 |
|---|---|---|
| `data/eda_cache/vision_manifest.parquet` | 1,737행 | 02 spec §9 스키마. `thumb_path` 100% 존재 |
| `data/eda_cache/thumbs/<폴더구조>/*.jpg` | 1,737장 | 1024px long-edge, JPEG q90 |
| 03 e2b 장면캡션 캐시 | (있으면) | P3_hybrid 결과 재사용, 없으면 재생성 |

**모델**(전부 설치·로컬, ollama 0.24.0 실측):
- 장소추정: `gemma4:26b`(17GB) — 사용자 지목(지리 사전지식 가설)
- 장면캡션 기준선: `gemma4:e2b`(7.2GB) — 03 P3_hybrid 재사용
- 임베딩: `qwen3-embedding:8b`(4.7GB) — 03 재사용

**제약**: manifest `exif_date` 보유 46.4%(png 594장 전량 날짜 결손). 사진별 순수 `taken_at` 그룹핑은 절반만 커버 → **그룹핑은 폴더 우선**(§3).

## 3. 그룹핑 & 정답 누출 차단

- **그룹키**: `folder_top` → (해당 그룹에 `taken_at`/`exif_date` 있으면) **날짜로 세분**. 날짜 결손 사진은 그 폴더를 1그룹으로 둔다.
  - 근거: 평가풀 정답 폴더는 전부 trip 단위(`2019_이탈리아`·`2022_아이슬란드`·`200620_23_제주`)라 폴더 자체가 "같은 장소·시점 묶음". 100% 커버되고 날짜 결손과 무관하다.
- **정답 누출 차단(중요)**: 그룹핑·평가에는 `folder_top`을 쓰되, **26b 추정 입력은 썸네일 픽셀만**이다. 폴더명·지명 텍스트를 프롬프트에 절대 넣지 않는다(넣으면 "추정"이 아니라 정답 복사). 폴더명은 오직 ① 그룹키 ② 평가 정답(weak label)으로만 쓴다.

## 4. 분석 항목

### §0. 셋업
manifest·썸네일·(있으면) 03 e2b 캡션 캐시 로드, Ollama 클라이언트, `seed=42`. 모든 I/O는 try/except flag-skip(01–03 패턴 계승).

### §1. multi-image 종합추론 스모크 테스트 (선행 게이트)
`gemma4:26b`에 같은 묶음 2–3장을 `images` 배열로 입력 → 응답이 **여러 장을 종합**했는지 확인(한 장만 보거나 장을 독립 처리하지 않는지). 서로 다른 장소 2장을 넣어 "두 장면이 다르다"는 인식이 나오는지 등으로 판별.
- **PASS** → §2를 직접 multi-image로 진행.
- **FAIL** → **montage fallback**: 묶음 N장을 1장 그리드로 합성해 단일 입력. (이후 §2 동일.)

### §2. day-place 추정 (A/B, 26b)
- 그룹별 **대표 N=6장**을 `taken_at` 시간순 균등 간격으로 샘플(하루/폴더를 대표). 6장 미만이면 전량.
- 6장 → `gemma4:26b` multi-image → **coarse 지명**(시/도·국가 수준). **공격/보수 2프롬프트**(§9) 각각.
- 그룹→(공격지명, 보수지명) 매핑을 캐시 parquet.

### §3. 결합·임베딩
- 각 그룹의 day-place를 그룹 내 **전 사진**에 전파.
- 검색 텍스트 = **03 e2b 장면캡션 + `\nLocation: {place}`** 결합. 비교군별로 별도 텍스트 생성.
- `qwen3-embedding:8b`로 임베딩 → 캐시. **비교군 3**: `e2b 단독`(03 기준선) / `+place 공격` / `+place 보수`.

### §4. 평가 (recall) + 보강 판정
- 평가풀 ~400(질의 정답 폴더 전부 + 디스트랙터), 한국어 질의 **03 질의셋 재사용**.
- 질의 임베딩 → top-k → **recall@5 / @10 · MRR**, 비교군 3 간 비교.
- **지명질의 세부**: 03에서 0.00이던 제주·일산 질의에 집중해 개선폭 측정.
- **day-place 정확도**: 추정 지명이 정답 폴더 지명과 일치한 그룹 비율.
- **환각율**: 틀린 지명이 부착된 그룹/사진 비율 — **공격 vs 보수** 대비.

## 5. 비용 전략

- **평가풀이 덮는 폴더/day만** 26b 추정(전체 1,737 재캡션 아님). 26b는 그룹당 multi-image 1회 × A/B 2회.
- **03 e2b 장면캡션 재사용**으로 장면 캡션 재생성 회피(변수는 day-place 하나로 통제).
- **캐시 parquet**(장면캡션·place·임베딩): 중단 시 캐시 기준 재개.
- 노트북에 26b multi-image wall-clock 실측 보고(콜드/워밍 분리).

## 6. 산출물 / 핸드오프

- **노트북**: `notebooks/04_day_geocaption_eda.ipynb` — 썸네일·캡션 임베드 → **gitignore**(ADR-0001)
- **findings 갱신**: `docs/01_eda_findings.md` 새 섹션 **§9 "Day-level 장소추정 캡션 보강"** — 스모크 결과·day-place 정확도·환각율·비교군 recall·권고
- **INGEST**(AGENTS.md): `wiki/data-profile/eda-findings.md`, `wiki/models/model-decisions.md`(캡션 보강 status)
- **ADR로 flag**(결정은 사용자, Claude 자동결정 금지):
  - 지명 보강(day-place) v1 채택 여부 및 공격/보수 강도
  - 장소추정 모델(gemma4:26b vs 권고 Qwen3-VL) 방향

## 7. 완료 기준

이 노트북이 다음을 답하면 완료:
1. §1 스모크로 **multi-image 방식 확정**(직접 입력 / montage fallback)
2. day-place 추정 **정확도·환각율**(공격 vs 보수) 정량
3. 비교군 3 **recall(@5/@10·MRR)**, 특히 **지명질의(제주·일산) 개선폭**
4. 공격↔보수 **recall–환각 trade-off** + 권고를 findings에 보존

## 8. 에러 처리 & 재현성

- Ollama 호출·디코드·임베딩 실패는 **flag 후 skip, crash 금지**(01–03 계승)
- `seed=42` — 샘플 선정·질의 매칭 결정적
- 캡션·place·임베딩 캐시 parquet, 실패 목록 표로 표시

## 9. 프롬프트 A/B 명세 (전부 영어 출력)

공통: 묶음 N장 입력, **coarse 단위**(시/도·국가 수준, 시군구 이하 금지), 폴더명·메타 미제공.

| 변형 | 의도 | 방향 |
|---|---|---|
| **공격(aggressive)** | recall 상한 | 단서(지형·식생·건축 스카이라인·하늘·표지판)로 **가장 그럴듯한 시/도·국가를 반드시 추정**해 적는다 |
| **보수(conservative)** | 환각 억제 | **명확히 식별될 때만** 지명을, 불확실하면 `unknown` |

구체 문구는 구현 시 노트북 상수로 확정.

## 10. 평가 방법 상세

- weak label = `folder_top`. recall@k = 질의 top-k에 정답폴더 사진이 든 비율. MRR로 순위질 보강.
- **프롬프트 간(=비교군 간) 상대 비교가 1차 목적**(절대값은 weak label·풀 한계로 참고, 절대 임계 없음 — 03 계승).
- day-place 정확도·환각율은 (규칙 매칭 + 필요시 정성 검토)로 그룹 단위 산정.
- macOS 한글 **NFD→NFC 정규화** 필수(`folder_top` 매칭 — 03에서 미적용 시 한글 질의 전부 recall 0 발생·교정).

## 11. 비범위 (다음/별도)

- **image-embedding leg**(D20 image kind: SigLIP/CLIP/Qwen3-VL-Embedding) — 별도 세션
- 장소추정/캡션 **모델 A/B**(Qwen3-VL vs gemma) — 골든셋 있는 빌드 ⑤
- **한국어 캡션 생성**(D19 영어 고정)
- **fine-grained 지명**(시군구 이하) — coarse만 검증
- **본 인덱싱 파이프라인 통합**(빌드 ③+)

## 12. 가정 & 미해결

- 폴더가 "장소 묶음"으로 충분(trip 폴더 전제). 큰 폴더(이탈리아 583장 다중 도시)는 coarse(`Italy`)로 뭉쳐도 골든셋 질의 입도와 부합한다고 가정.
- `N=6` 시간순 균등 샘플이 그룹 대표로 충분. 부족 신호 시 N 조정.
- multi-image 종합추론 가능(§1 스모크로 검증, 실패 시 montage).
- coarse 지명이 골든셋 질의 입도(제주 수준)와 일치.
- day-place 정확도 산정에 폴더명을 약(弱)정답으로 사용. 다의·노이즈 폴더는 보정/제외.

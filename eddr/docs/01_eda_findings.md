# EDDR EDA 최종 리포트 — 구현 전 가정 검증

> 작성일 2026-05-31 · 출처 `notebooks/01_eda.ipynb` · 라이브러리 9,047 assets

## 1. 요약 (TL;DR)

- 실제 Photos Library **9,047 assets** 중 `D18` 제외 규칙 적용 후 **INDEXABLE 8,574장(94.8%)**.
- 메타데이터(좌표·시각·구조) 기반 핵심 가정 **6건 중 5건 VALIDATED · 1건 관찰** — 인덱싱 파이프라인(`D18`), GPS 기반 Trip/Daily Radius(`D14`/`D15`), recent-first 타임라인(`D22`)을 **설계대로 진행 가능**.
- 이번 세션은 **메타데이터 검증에 한정**. 픽셀/로컬파일 기반 항목(Vision, dedup 실측, iCloud 다운로드, Trip 심화)은 **다른 세션**으로 분리.
- EDA가 촉발한 두 결정은 **`ADR-0004`** 에 기록: **near-dup 처리 v1 보류(`D8`)**, **Person 기반 질의 v1 폐기(`D10`)**.

> 판정 요약: 메타데이터 가정 **VALIDATED 5 · 관찰 1**, 별도 결정 **2건(ADR-0004)**, 다른 세션 이관 **4건**.

## 2. 데이터 개요

총 9,047 assets = 사진 8,694 + 동영상 353. 기간 2012–2026(활성 2016~), 최다 2022년 1,535장 · 2021년 1,362장 · 2025년 1,189장. 보정본 3,380장(전체의 약 37%)은 모두 원본과 동일 UUID 1행 유지(`ADR-0002` 확인, UUID 유일성 assertion 통과).

### 2.1 INDEXABLE 제외 waterfall (`D18` / `D9`)

| 단계 | 잔여 | 제외 |
|---|---|---|
| 전체 assets | 9,047 | — |
| − 동영상 | 8,694 | 353 |
| − hidden | 8,694 | 0 |
| − burst non-keeper | 8,692 | 2 |
| − screenshot | 8,584 | 108 |
| − document scan(앨범 휴리스틱) | 8,584 | 0 |
| − <300px(원본) | 8,574 | 10 |
| **INDEXABLE** | **8,574 (94.8%)** | |

과대제외 없음. Live Photo 정지본은 유지(`ADR-0002`).

### 2.2 포맷 분포

HEIC 6,645(77.5%) · JPEG 1,813(21.1%) · RAW(Panasonic 34 · Olympus 29 · Adobe 1 · Fuji 1) · PNG 28 · GIF 19 · WebP 3 · TIFF 1.

## 3. 가정별 검증 (메타데이터)

### 3.1 INDEXABLE 비율 — `D18` / `D9` → **VALIDATED**
8,574 / 9,047(94.8%). 제외 규칙이 소수만 걸러냄(동영상 353 외 hidden 0 · burst 2 · screenshot 108 · <300px 10). 규칙 자체 조정 불필요.

### 3.2 GPS 커버리지 — `D14` / `D15` → **VALIDATED**
INDEXABLE의 **91.0%**(7,801장)가 좌표 보유. 2021년 이후 약 97–98%로 안정. 2019년이 67.4%로 최저(특정 카메라 사용 추정), 2016년 이전(누적 27장 미만)은 0%. Trip 세그먼트·Daily Radius KDE의 상류 가정 충족.

### 3.3 taken_at 유효 / recent-first — `D22` → **VALIDATED**
taken_at **100% 유효**(미래 날짜 0 · 1970 sentinel 0). 최근 12개월 **1,113장** = recent-first 1차 배치 규모로 적정.

### 3.4 후보 Trip feasibility — `D14` → **VALIDATED** (심화 분석은 별도 세션)
집 중심 50km · 24h 연속 기준으로 **후보 Trip 44개** 자동 검출. 최장은 2019-06-29~07-12(약 13.5일, 264장, 최대거리 약 9,000km)로 장거리 해외 trip. 사람이 다룰 규모이며 세그먼트 알고리즘이 동작함을 확인. 단, 노트북은 44개 중 20개만 출력했고 파라미터 민감도·경계 품질은 미검토 → **별도 세션**에서 심화.

### 3.5 Daily Radius 군집 — `D15` → **VALIDATED**
좌표 밀도에 뚜렷한 peak 존재. 최대 밀집은 **서울 강남·서초 일대**(단일 격자 730장), 비서울 최대 클러스터는 **아이슬란드**(약 180장). 집/주요 거점이 KDE·양자화 클러스터링으로 분리 가능.

### 3.6 no-GPS dated — `D14` → **관찰**
좌표 없는 dated 사진 **773장(INDEXABLE의 9%)**. 위치로 Trip 배정 불가. 시간근접 배정 가능성 측정은 **별도 세션**(`D14` 심화)으로.

## 4. 범위 밖 / 후속 세션

이번 세션에서 다루지 않음(결정이 아닌 후속 작업, 별도 세션 예정):

- **`D14` Trip 심화** — 전체 44개 프로파일 · 파라미터 민감도 · no-GPS 773장 배정 · 경계 품질.
- **`D12` 로컬파일/iCloud EDA** — INDEXABLE 중 로컬 파일 보유는 **2.7%(232장)**, 나머지는 iCloud-only. 이는 Optimize Storage의 **의도된 동작**이며 on-demand 다운로드(`D12`) 전제. 픽셀 기반 EDA는 별도 세션.
- **`D19` / `D20` Vision** — S11(`RUN_VISION=False`)로 미실행. 한국어 질의 ↔ 영어 caption multilingual embedding 검증은 별도 세션.
- **`D8` 실제 near-dup 측정** — §5 참조(아래 결정의 후속 측정).

## 5. EDA가 촉발한 결정 → `ADR-0004`

아래 두 측정 사실에 근거해 결정을 내렸으며, 상세는 [`docs/adr/0004-eda-driven-scope-decisions.md`](adr/0004-eda-driven-scope-decisions.md)에 기록한다.

- **near-dup (`D8`)** — 디스크 샘플의 near-dup 93쌍은 전부 export가 만든 `(1)` 복사본 아티팩트(Hamming 0)였고, **라이브러리 실제 near-dup율은 미측정**. → **v1 보류**(일단 중복 허용).
- **Person (`D10`)** — named person이 **단 1명**, INDEXABLE의 **12.3%**(약 1,050장)에만 존재. R2 person 질의 recall이 구조적으로 불가. → **v1 폐기**.

## 6. 부록

### 6.1 발견 ↔ 노트북 셀 매핑
S1 메타 로드(9,047) · S2 제외 waterfall(8,574) · S3 GPS(91.0%) · S4 timestamp(100% / 1,113) · S5 person(12.3% / 1명) · S6 포맷 · S7 로컬 export(2.7%) · S8 near-dup(아티팩트) · S9 Daily Radius 군집 · S10 Trip(44 / 773) · S11 Vision(미실행) · S12 요약(VERDICT 본 리포트에서 확정).

### 6.2 규모 노트
라이브러리 실측 약 9,047장은 설계 목표 "~10만 장"의 약 1/11. 성능·처리량 추정은 보수적으로 잡혀 있어 위험은 아니나, 추정 재보정 시 반영 권장.

---

## 7. 풀데이터셋 EDA (02 notebook, 2026-06-03)

> 작성일 2026-06-03 · 출처 `notebooks/02_full_dataset_eda.ipynb` · 라이브러리 9,054 assets + 로컬 1,738 파일

### 7.1 스코프

iCloud 메타 전수(**9,054 assets = 이미지 8,701 + 동영상 353**; 02 노트북은 이미지 8,701만 처리) + 사용자 추가 로컬 아카이브(1,737 실픽셀 이미지, PSB/PSD/zip/동영상 제외). Ollama 미실행 — 근거데이터 확보까지.

### 7.2 규모 정정

iCloud 실측 9,054(01 시점 9,047 +7, 라이브러리 live). **"~10만"은 약 11배 과대추정.** 보정 총 풋프린트 ≤ 10,365 (iCloud 9,054 ∪ icloud_new 1,311). 단 icloud_new는 **파일명 매칭 기반 저신뢰 상한**(리네임 시 과대) — 정밀 추정은 timestamp 매칭으로 다음 세션.

### 7.3 정합성 (로컬 ↔ iCloud)

| 버킷 | 수 | 비율 |
|------|----|----|
| overlap (파일명 매칭) | 427 | 24.6% |
| icloud_new (로컬 전용) | 1,311 | 75.4% |

overlap 427 / icloud_new 1,311, 매칭률 24.6%(파일명 floor). DSC/DSCF(전용카메라)는 전부 icloud_new — 카메라 직송 추정.

### 7.4 로컬 EXIF

date 보유율 46.4%, **GPS 0.1%(사실상 0)** → 위치는 폴더명·iCloud 매칭에 의존(폴더-컨텍스트 설계 정당화).

### 7.5 실 near-duplicate (D8 최초 측정)

BLAKE3 정확중복 14파일, dHash Hamming≤1 **919쌍 (전체 쌍의 0.0610%)**, cross-folder 334쌍(36.3%, 여행 백업 패턴). → ADR-0004 D8(보류) 결정에 실측 근거 보강.

### 7.6 해상도

bimodal — png 저해상 집단 + 사진 고해상 집단. 중앙값 1.7MP는 png 집단 영향이라 단일값 해석 주의.

### 7.7 핸드오프 (다음 세션 Ollama)

`data/eda_cache/vision_manifest.parquet`(1,737행 → 02 재실행으로 **3,122행**, §7.9; spec §9 스키마 + `source` 컬럼) + 폴더구조 유지 썸네일 `data/eda_cache/thumbs/` 준비 완료.

> **프라이버시(ADR-0001)**: 매니페스트는 매칭된 iCloud 정밀좌표 26행(`gps_lat/lng`)과 인명 추정 폴더명(예 `하율`)을 포함한다. `data/`는 gitignore라 현재 미커밋 — **로컬 처리 전용**. 다음 세션이 캡션/임베딩을 외부 서비스로 보낼 경우 좌표·PII는 반드시 마스킹.

### 7.8 ADR flag (결정은 사용자)

1. **규모 정정**: ~10만→9,054+로컬(보정 풋프린트 10,365) — 설계 규모 가정 재검토 필요.
2. **icloud_new ~75%의 D12·D16 영향**: 로컬 파일의 75.4%가 iCloud에 없음 → iCloud=SoT(D12) 및 asset=identity(D16) 결정의 경계 조건 재검토.
3. **실 near-dup율 → D8 재검토**: 919쌍(0.061%) 실측됨 — v1 보류(ADR-0004) 유지 여부 사용자 판단.

### 7.9 google_takeout 3번째 소스 (`ADR-0005`, 2026-06-04 편입)

`icloud`·`local`에 이은 3번째 소스 `source='google_takeout'`를 02에 편입(재실행). Takeout staging 결과(`data/google_photos/manifest.jsonl`, 1,385장)를 독립 프로파일링하고 vision_manifest에 합류. **맥 보관함과 날짜분리[2011,2017)이므로 cross-source dedup·overlap은 미수행**(`ADR-0005` 트레이드오프 존중) — icloud↔local 정합성(§7.3)과 달리 takeout은 독립 집계만.

**독립 프로파일** (manifest 1,385):

| 항목 | 값 |
|---|---|
| 연도 분포 | 2011:42 · 2012:3 · 2013:**815** · 2014:86 · 2015:254 · 2016:185 |
| 기간 | 2011-02-17 … 2016-06-03 |
| GPS 보유 | 4.5% (62장; 2011–2016 카메라 GPS 희박) |
| description | 0% (비전 단계서 생성 예정) |
| 포맷 | jpg 1,350 · jpeg 27 · gif 7 · png 1 |

**3-소스 통합 인벤토리**:

| 소스 | 수 | 비고 |
|---|---|---|
| icloud | 8,701 | Photos Library 이미지(자산 9,054) |
| local | 1,738 | overlap 427 / icloud_new 1,311 |
| google_takeout | 1,385 | gap-fill [2011,2017), 날짜분리 |

보정 풋프린트 **10,365 → +takeout 11,750**(dedup 미수행이라 단순합 상한; 맥 2012–2016 산발 225장과의 경계 중복은 의도적 수용·미측정).

**vision_manifest 갱신**: 1,737 → **3,122행**(local 1,737 + takeout 1,385). 스키마에 `source` 컬럼 신설(`local`/`google_takeout`). takeout 썸네일은 `thumbs/google_takeout/<content_hash>.jpg` 별도 네임스페이스, decode 캐시 `takeout_files_meta.parquet` 분리(로컬 near-dup 측정 §7.5 오염 방지).

**03·04 영향**: 03(프롬프트 선택 EDA)은 §0에서 `source=="local"` 가드로 1,737만 사용 — D19 PASS(§8.5) 보존. 04는 갱신된 3,122 manifest 기반으로 재실행됨(평가풀 변동 주의 §9.7). takeout 실제 캡션은 빌드 ⑤ 비전 단계에서.

---

## 8. Vision 캡션 프롬프트 EDA (03 notebook, 2026-06-04)

> 출처 `notebooks/03_vision_caption_eda.ipynb`(gitignore) · spec `docs/superpowers/specs/2026-06-03-vision-caption-eda-design.md` · **전부 로컬 Ollama, 외부 전송 0(ADR-0001)**

### 8.1 스코프·방법
02 핸드오프(`vision_manifest` 1,737 + thumbs)로 **D19/D20 검증**. 정성(24장 × 3프롬프트 × 2모델 = 144캡션) → 정량(평가풀 ~400, 한국어 질의 10개, 검색 recall). 캡션 gemma4(e2b/26b), 임베딩 qwen3-embedding:8b(4096d). 프롬프트 3종: P1 간결 / P2 구조화슬롯 / P3 하이브리드(서술+키워드).

### 8.2 처리량 실측
**e2b 8.3s/장 · 26b 18.6s/장**(워밍). 콜드스타트(첫 호출 e2b 7.7s·26b 33.5s) 분리. → 무차별 전수 캡션 회피, 2단계+캐시 설계 정당화.

### 8.3 선행 픽셀(§1)
png 594의 edge-variance 중앙 **1594 vs jpg 1146(+37%)** — png=편집·캡처본(텍스트·그래픽 혼재). 저조도·흐림 등 "어려운 후보" 299장. 샘플 24에 png 10·hard 7 의도 포함(약점 노출 층화).

### 8.4 정성 캡션(§2)
평균 길이: P1 ~90자 · P2 ~830자(슬롯 충실, **e2b는 `**Place:**` 마크다운 노출=노이즈**) · P3 ~210자(서술+키워드, 깔끔). **26b 정확**(반딧불이·"pink jacket"·차내맥락 포착), **e2b 환각 경향**(어두운 장면: 반딧불이→나비/햇빛).

### 8.5 정량 recall(§3) — P3 > P2, **D19 PASS**
e2b 기준, 평가풀 400(정답폴더당 30캡 + 디스트랙터):

| 프롬프트 | recall@5 | recall@10 | MRR |
|---|---|---|---|
| P2_struct | 0.30 | 0.60 | 0.285 |
| **P3_hybrid** | **0.50** | **0.70** | **0.340** |

→ **best = P3_hybrid**(키워드 명시가 검색 우위). **D19 PASS**(recall@10 0.70 ≥ 0.5): 영어 캡션 + multilingual 임베딩으로 한국어 질의 매칭 작동.

### 8.6 통찰 — 캡션검색의 "지명 약점"
질의별 recall@10: **이벤트·시각특징 강**(결혼식·아이슬란드·이탈리아·개심사·방콕 = 1.00), **고유지명 약**(제주도·일산호수공원 = 0.00). 영어 캡션이 `Jeju`·`Ilsan`을 못 담아, 시각적으로 평범한 풍경 질의는 디스트랙터와 안 갈림. → **캡션검색은 "무엇이 찍혔나"에 강, "어디서"에 약** → 지명 질의는 GPS·폴더명·trip 메타로 보완(PLAN D14·geocode를 실측 정당화).

### 8.7 best 프롬프트 전문 (P3_hybrid, 영어 출력)
```
Describe this photo in English in 1-2 sentences, then list 5-10 searchable keywords (nouns: places, objects, events, food, activities).
Format:
Caption: <sentence>
Keywords: <comma-separated>
```

### 8.8 함의·미해결
- **모델**: 이번은 e2b로 프롬프트 검증. 26b 정확하나 2.2배 느림. 권고 Qwen3-VL A/B는 ⑤단계(골든셋).
- **recall 절대값**은 weak label(폴더)·풀 한계 — **P3>P2 상대순위가 결론**.
- **macOS 한글 NFD**: `folder_top` 매칭 시 NFC 정규화 필수(미적용 시 한글 질의 전부 recall 0 — 03에서 실제 발생·교정).
- image-embedding leg(D20 image kind)·한국어 캡션 생성은 비범위.

### 8.9 결정 (사용자 확정 2026-06-04)
- **D19(영어 캡션) 유지 확정** — 검증 PASS. 단 지명 질의 약점은 GPS/trip 메타 보완 전제.
- 캡션 프롬프트 **P3_hybrid 확정** — ⑤ 구현 기본값.

### 8.10 프롬프트 A/B 실데이터 재검증 (빌드 ⑤ prompt-ab, 2026-06-08)
빌드 ⑤에서 §8.9 확정 P3_hybrid에 변형 **P3_hybrid_v2**(4섹션 구조화)를 더해 **실데이터** A/B(`eddr vision prompt-ab`, 소스별 stratified). 부분 materialize 4,208장(google_takeout 1,385 + local 1,730 + photos_library 1,093)에서 50장(소스 17/17/16) 캡션, `processed=50 failed=0`, 민감정보 누출 0.

**정량(텍스트 지표)**: v2 4섹션 구조 100%·평균길이 2.4×(955 vs 395자)·헤징 7×. 그러나 **지역·장소 단정 v2 14 vs hybrid 4**(헤징 없는 단정 v2 5 vs hybrid 0) — v2가 구조적이나 위치를 더 과감히 단정.

**픽셀 ground-truth(3장, 사용자 승인 하 Claude 비전 — 본 절 유일한 외부 전송, ADR-0001 예외)**: 2011 일본여행 컷에서 신사 手水舎 국자 글자 **奉納**(일본 한자) → v2 "Korean" 환각·hybrid "Chinese" 근접; 야간 도시 간판 **アパート**(가타카나, 일본) → v2 "Seoul/Korean" 환각·hybrid "Japan" 정확, 거의 동일한 중복 컷을 v2가 "한국"·"일본"으로 자기모순.

**결론**: v2는 **촬영자 모국(한국)을 환각 투영**, 위치 단정 신뢰 불가. §8.6 "지명 약점"을 격상 — 캡션은 지명에 약할 뿐 아니라 *틀린 위치를 환각*한다. "어디서"의 권위는 GPS/trip 메타(빌드 ④/⑥), 캡션 위치 단정은 인덱싱·답변에서 배제. **§8.9의 P3_hybrid 기본값 선택을 뒷받침**(v2 미채택, 채택 시 Context cues 위치문장 제거 필요). 근거: `data/eda_cache/vision_prompt_ab_n50.jsonl`.

---

## 9. Day-level 장소추정 캡션 보강 EDA (04 notebook, 2026-06-04)

> 출처 `notebooks/04_day_geocaption_eda.ipynb`(gitignore) · spec `docs/superpowers/specs/2026-06-04-day-geocaption-eda-design.md` · plan `docs/superpowers/plans/2026-06-04-day-geocaption-eda.md` · **전부 로컬 Ollama, 외부 전송 0(ADR-0001)**

### 9.1 스코프·동기
03의 "지명 약점"(§8.6: 제주·일산 recall@10 **0.00**)을 **캡션 경로로 보완** 시도. 가설(사용자 제안): `gemma4:26b`가 **day 묶음 multi-image** 단서 + 지리 사전지식으로 coarse 지명(`제주도` 수준)을 추정해 e2b 캡션에 주입하면 지명 질의가 검색된다. image-embedding leg(D20)는 별도 세션으로 분리. 03 자산(평가풀 캡션·질의·`recall_mrr`) 재사용으로 03과 직접 비교.

### 9.2 multi-image 스모크 — PASS
`gemma4:26b`에 서로 다른 2장 동시 입력 → 두 장면을 번호로 분리 기술(녹색 잎 근접 / 흑백 사구). **Ollama multi-image 종합추론 작동 확인** → montage fallback 불필요, 직접 multi-image 채택.

### 9.3 day-place 추정 (29그룹, 공격/보수 A/B)
평가풀 400장 → 폴더→day 그룹핑 **29그룹**. 그룹별 대표 6장 multi-image → coarse 지명. **공격**(반드시 추정)·**보수**(확신 시만, 아니면 `unknown`). 추정 wall-clock **1373s(23분, 에러 0)**. 정답 누출 차단(추정 입력=썸네일 픽셀만, 폴더명 미주입).
- 정확 예: 제주→`Jeju Island` · 아이슬란드→`Iceland` · 이탈리아→`Dolomites` · 방콕→`Bangkok` · 몽골(영문)→`Tuv, Mongolia`.
- **환각 예**: 부산 폴더→`Jeju` · 몽골(한글)→`Colorado` · 결혼식→`Jeju` · 인물 폴더(은지/하율)→`Busan`/`Dolomites`.

### 9.4 결과 — recall (비교군 3, 03 질의셋 10개 재사용)
| arm | recall@5 | recall@10 | MRR |
|---|---|---|---|
| e2b_base (03 기준선) | 0.3 | 0.6 | 0.285 |
| +place_aggr (공격) | **0.5** | 0.6 | **0.468** |
| +place_cons (보수) | 0.4 | 0.5 | 0.384 |

- **지명질의(제주·일산)**: 3개 arm 모두 **recall@10 0.00** — 보강 실패.
- 보강 순효과: recall@10 **불변**(base=aggr 0.6), 보수는 **악화**(0.5). 개선은 recall@5·MRR(랭킹)에 국한.

### 9.5 환각율
- **공격**: 29 전건 추정 · alias 적중 7 · 환각후보 22 · unknown 0.
- **보수**: 14 추정 · 적중 6 · unknown 15.
- (단 `South Korea` 등 coarse 정답이 alias 미수록으로 환각 집계 — 과대 가능. 명백 환각: 부산·몽골·인물 폴더.)

### 9.6 핵심 결론
1. **단순 day-place 캡션 주입은 지명 약점을 못 고친다.** 제주는 정답 라벨을 받고도 **환각 `Jeju`**(부산·결혼식 폴더)와 경쟁해 top-10에서 묻힌다 — **정밀도 없는 recall 보강은 무효**.
2. day-place는 **"부익부"**: 이미 강한 해외 유명지의 랭킹은 올리나(recall@5·MRR↑), 약점(제주·일산·부산·몽골)은 환각이 오히려 갉아먹는다.
3. **함의**: 지명 질의 보완은 캡션 지능화가 아니라 **GPS·trip 메타(D14)**가 정도 — §8.6 결론이 강화됨. 캡션 보강을 살리려면 **환각 통제(정밀도)가 선결**.

### 9.7 평가 주의
- **base 0.6 vs 03 P3 0.70 불일치**: 부산·몽골이 03 hit→04 miss, 단양은 반대(순 −1). 원인은 세션 중 **평가풀 갱신**(`vision_manifest` 1737→3122 Google Takeout 통합, `pool_captions_03` 800행→dedup 400). **상대비교(04 내부 aggr vs base)는 동일 풀이라 유효**하나, 향후 회귀 시 평가풀 고정 필요.
- macOS **NFD/NFC** 함정 재발: `emb_df.folder_top`(NFD) vs 질의(NFC) → 최초 recall 거의 0, NFC 정규화로 교정(§8.8 교훈 반복).

### 9.8 결정 (ADR flag, 사용자 확정 2026-06-04)
- **day-place 캡션 보강 v1 보류** — 순효과 미미·환각이 발목. 지명 질의는 **D14 메타 경로(GPS·trip)**로 푼다.
- image-embedding leg(D20)·환각 통제 후 재평가는 별도 세션 후보.

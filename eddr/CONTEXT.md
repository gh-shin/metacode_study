# CONTEXT — EDDR

> 도메인 용어집(glossary). 구현 디테일은 여기에 적지 않습니다 — `docs/PLAN.md` 및 ADR로.

---

## Glossary

### Trip (여행)

사용자의 **일상 반경 밖**에서 **24시간 이상 연속 체류**한 사진 cluster.

- 1박 2일 이상의 모든 외출을 Trip으로 인정 (e.g., 강원도 주말 여행 포함).
- **국경을 넘어도 일상 반경에 복귀하기 전까지는 1개 Trip** (e.g., 인천 → 로마 → 뮌헨 → 인천 = 1 trip, [[trip-country]] 2개).
- "일상 반경"의 정의는 *미정* — 자동 추정 vs 사용자 입력 결정 대기.

**Not a Trip:**
- 같은 도시 내 일일 외출 (낮 카페·식당 방문)
- 일상 반경 내 사진 (출퇴근, 동네 산책)

### Trip-Country

하나의 [[trip]]에 속한 방문 국가. Trip ↔ Country는 M2M.

- 시나리오 C (방콕 → 시엠립 → 방콕)는 1 trip / 2 countries.
- 입국 순서·체류 기간은 v1엔 보존하지 않음 (사진의 `taken_at` + 좌표로 도출 가능).

### Person (인물)

[[photo]]에 등장하는 사람. **Photos.app에서 named된 person만 import** (verified + suggested + confirmed).

- Photos.app의 person UUID로 식별 (동명이인 구분). EDDR `persons.photos_person_uuid` column 필요.
- Hidden persons (Photos.app에서 숨김 처리)는 제외.
- Unnamed face cluster, EDDR 자체 얼굴 인식은 *안 함* (D2, D10).
- 사용자가 Photos.app에서 라벨링 추가/변경 시 `eddr update` 명령 시 `photo_persons` 전체 re-import.
- 라벨 미작업 가족·친구는 R2 답에서 누락 — setup wizard에서 안내.

### Indexing Lifecycle

약 9,054장(실측 — 초기 "10만" 가정은 약 11배 과대) 첫 인덱싱부터 점진 업데이트까지의 사용자 시점 흐름.

- **첫 사이클: Recent-first batch + background continue.**
  - 최근 1년치 사진을 먼저 인덱싱 (수십 분 ~ 1시간).
  - 사용자는 그 후 즉시 query 가능.
  - 나머지 (전체)는 백그라운드 진행.
- **점진 사이클 (`eddr update`)**: 신규/변경된 사진만 처리.
- **Resume**: 단계별 status를 photo row에 기록(`indexing_status`). 중단 후 재실행 시 status 기준 skip.
- **Trip clustering**: 인덱싱 milestone마다 (예: +1만 장) 재클러스터. 사용자 명시 `eddr update --recompute-trips`로도 트리거.
- **LLM 답변 UX**: 답 footer에 "현재 인덱싱 상태: N/M 사진" 표시. 답이 인덱싱 미완료에 의해 부분적일 수 있음을 LLM이 인지·반영.

### Photo (사진)

EDDR이 관리하는 1개의 logical photo entity. **Photos Library asset이 identity의 source of truth** ([ADR-0002](docs/adr/0002-photo-identity.md)).

- Photos Library asset 1개 = 1 photo. `source_uri` = Photos UUID.
  - 원본/보정본 = 같은 Photos asset = 1 photo. variant 정보는 v1에 보존 안 함.
  - Burst는 keeper(`burst_selected`)만 1 photo.
  - Live Photo는 정지 이미지만 사용 (영상 부분 무시).
- 로컬 파일 1개 = 1 photo. `source_uri` = 절대 경로.
- 로컬 파일의 BLAKE3가 Photos Library 어느 asset과 일치 → 로컬 파일 skip (Photos 우선, D4).
- iCloud Shared Library 사진도 포함 (가족이 추가한 사진 등 owner 무관, Photos.app에 보이는 모든 asset).

**Photo가 아닌 것 (인덱싱 제외):**
- Photos hidden 사진
- Burst non-keeper
- Video (mp4/mov) 및 Live Photo 영상 부분
- Screenshots (`is_screenshot=True`)
- Document scans (Photos.app "Documents" album)
- 매우 작은 이미지 (예: 300×300 미만)

### Near-duplicate (거의 동일)

BLAKE3는 다르지만 dHash가 가까운 두 [[photo]]. 같은 장면의 다른 binary (e.g., HEIC와 export된 JPG, 또는 다른 해상도).

- 양쪽 다 인덱싱하되 `near_duplicate_group_id`로 묶음.
- UI는 그룹 당 1장만 노출, "비슷한 사진 더 보기" 옵션 제공.
- "dHash 한 단위 차이" cutoff(D8)의 적절성은 인덱싱 후 검증 (튜닝 가능). **02 실측: Hamming≤1 919쌍(전체 쌍의 0.061%) — 낮아 v1 near-dup 처리 보류(ADR-0004)**.

### Caption (캡션)

[[photo]]의 시각적 내용을 자연어 텍스트로 묘사한 것. 로컬 vision-language model이 생성.

- **언어: English 1개만** (vLM 한국어 품질 risk 회피). Claude이 한국어 답을 만들 때 영어 caption을 읽고 한국어로 풀어냄.
- **프롬프트: P3_hybrid 확정** (1~2문장 서술 + 검색용 키워드 목록). 03 EDA에서 한국어 질의 검색 **D19 PASS**(recall@10 0.70). → [findings §8](docs/01_eda_findings.md)
- **강약점**: 캡션검색은 *무엇*(이벤트·객체·음식)에 강하고 *어디서*(고유지명 — 제주·일산 등)에 약하다(영어 캡션이 한글 지명을 못 담음). 지명 질의는 GPS·[[trip]]·폴더명 메타로 보완.
- 1 photo = 1 caption (v1).
- caption text는 사용자 query 답변 시 [[privacy-boundary]] 정책에 따라 외부 LLM에 전송됨.

### Embedding (임베딩)

[[photo]]의 검색용 벡터 표현. 1 photo당 2개 보유 (= 두 갈래, "leg"):

- **Image embedding (image leg)**: 사진 픽셀로부터 직접 생성. 시각적 유사성 검색용. **03 미검증**(D20 image kind — 후속 EDA).
- **Caption text embedding (caption_text leg)**: [[caption]] 텍스트를 multilingual encoder로 변환. 의미적 검색용. **03에서 검증**(D19 PASS, P3_hybrid).

두 embedding 모두 동일 multilingual 공간(caption_text leg는 `qwen3-embedding:8b` 확정; image leg는 후속 → [[model-decisions]]). 사용자 한국어 query → 같은 인코더로 변환 → 양쪽과 거리 비교(현 구현은 Chroma 기본 L2; `qwen3-embedding` 정규화 벡터라 cosine과 순위 동일).

**Model versioning**: v1엔 single model_id. upgrade 시 전체 재생성.

### LLM Tool Surface — superseded (ADR-0009)

~~외부 LLM(Claude)이 EDDR DB에 접근하는 함수 인터페이스~~ — **D26으로 개념 소멸**(채팅·외부 LLM 폐기, [ADR-0009](docs/adr/0009-map-local-search.md)). `QueryService`(`search_photos`·`semantic_search_photos` 등)는 **내부 검색 서비스**로 존속하며 privacy 스키마·`limit` 강제 등 구현 규율은 계승, 시그니처는 변경 자유. 역사 기록: [ADR-0003](docs/adr/0003-llm-tool-surface.md).

### Query Extraction (질의 해석)

사용자 한국어 질의를 로컬 소형 모델(`gemma4:e2b`)이 구조화된 검색 조건으로 변환하는 단계 (D26).

- 출력: `keywords_en`(영어 — BM25용) · `date_from/to`(KST) · `countries/cities`(한국어 — geocode 표기와 일치).
- 실패 시 임베딩-only 폴백. UI는 해석 칩으로 추출 결과를 항상 노출(오추출 가시화).
- 임베딩 질의 자체는 원문 한국어 그대로(qwen3 multilingual + instruct prefix).

### Golden Set

v1 done의 기준. **10문항 중 8개 이상 통과 = MVP 합격.**

분포 (R1 무게중심):
- 5문항: R1 (trip + 좌표·시간 기반 사실 질의)
- 3문항: R2 (~~person 기반~~ — ⚠️ **ADR-0004로 person 질의 v1 폐기**, 분포 재정의 필요. 사용자 작업)
- 2문항: R3 (semantic search)

정답 형식: 질의 종류별 혼합.
- 사실 query → fact-list
- person query → photo_id list 또는 person 정답
- semantic query → photo_id list (recall@k 측정)

평가 방법: **검색 결과 기반 완전 자동 채점** (D26-⑤, ADR-0009 — 구 hybrid/LLM judge 대체).
- 사진형 → 정답 사진이 검색 결과에 포함되는가
- fact형(G04·G08 "언제 갔더라") → 정답 날짜 lane이 상위 노출되는가
- 회귀: `eddr golden`이 `POST /api/search` 경로로 10문항 일괄 기계 판정

작성 주체: **사용자 본인** (정답을 본인만 안다 — 골든셋의 전제). 문항별 match 규칙도 사용자가 작성(스키마는 시스템 제공). `docs/golden_set.yaml`로 commit.

### Privacy Boundary

EDDR이 외부로 데이터를 내보내는 경계. **D26부터 런타임 외부 LLM 호출 자체가 0회** — 경계의 본질은 "외부 LLM 미전송"이며, 정밀 좌표의 **"내 서버 → 내 브라우저" 노출은 허용**(지도 렌더용, ADR-0009 §3).

- **이미지 바이너리**: 외부 절대 미전송 (D6) — "내 서버 → 내 브라우저"만.
- **정밀 좌표** (lat/lng): 외부 미전송(Nominatim reverse 좌표는 종전 수용 범위). 로컬 브라우저 노출 OK.
- **Photos hidden 사진**: 인덱싱부터 제외 → DB에 없음 → 자연 미노출.
- **PII EXIF**(카메라 serial 등)·**파일시스템 절대경로**: 미노출.
- 수용한 외부 의존(D26): 지도 타일 좌표(OpenFreeMap) · 장소 검색어(Nominatim, 서버 프록시).

세부 정책: [ADR-0001](docs/adr/0001-privacy-boundary.md) + [ADR-0009 §3](docs/adr/0009-map-local-search.md).

### Note (메모)

사용자가 [[photo]]에 직접 남기는 한국어 자유 텍스트 — 사진별 1건 (D26 M5).

- 저장 즉시 임베딩(qwen3-embedding:8b → Chroma `eddr_note_text_v1` 별도 컬렉션)되어 검색([[embedding]] note leg)에 합류.
- [[caption]](vision 생성·영어)과 별개 — 메모는 사용자 작성·한국어·검색은 임베딩 leg만(FTS porter 부적합).
- G06류 "데이터 부재" 사진에 대한 기억 보강 수단(구 D24 enrichment의 구현 형태, 수동 위치 지정과 함께).

### Daily Radius (일상 반경)

[[trip]] 검출의 기준이 되는, 사용자의 일상 활동 영역. 다중 점/영역으로 표현 (집, 직장, 본가 등).

- 사진 좌표 분포를 density clustering 하여 후보 자동 추출.
- 사용자가 setup wizard에서 각 cluster를 라벨링·추가·삭제·반경 조정.
- v1은 단일 시점 정의만 보존 (이사 = v2 후보).
- 본가 같은 ambiguous case는 사용자 직접 결정 ("일상에 포함" 또는 "trip으로 인정").

# EDDR (어디더라?) — MVP 설계서

> 그릴링 세션 결과 합의된 1차 설계. v1 구현 착수의 기준 문서.
> 작성일: 2026-05-28 (grilling 반영: 2026-05-29)
> 도메인 용어집은 [../CONTEXT.md](../CONTEXT.md), 핵심 결정은 [./adr/](./adr/) 참조.

> ⚠️ **ADR-0004 반영(2026-06-01)**: 본 문서의 D8(near-dup 그룹핑)은 **v1 보류**, D10(person 질의)은 **폐기**되었다. 컬럼·테이블·골든셋 분포의 영향은 각 위치 주석 및 `wiki/decisions/eda-scope.md` 참조.

---

## 0. 한 줄 요약

내 사진(약 **9,054장** — iCloud 실측, EDA 02 기준. 초기 "~10만 장" 가정은 약 11배 과대추정. + 사용자 로컬 아카이브) 메타데이터와 이미지 분석 결과를 로컬 DB로 만들고, 자연어 질문을 받으면 LLM이 "언제, 어디서, 누구랑, 뭘 했는지"를 알.잘.딱. 답해주는 개인용 로컬 챗봇.

---

## 1. 배경 / 동기

- 여행과 사진을 좋아해 사진첩에 방대한 기록이 쌓였지만, 정작 필요할 때 "어디였더라?", "언제 갔지?", "누구랑 갔지?"가 떠오르지 않음.
- 가족/지인과의 대화에서 사실 확인이 필요한 순간이 잦음.
- 사진 메타데이터는 충분히 풍부하지만 사용자가 직접 검색·정리하기 어려운 형태.

## 2. 타겟 사용자 시나리오

**기준 시나리오 (R1)**
- 입력: "내가 몽골이랑 이탈리아 여행간 게 언제였더라?"
- 동작: 좌표·날짜 기반 trip 검색
- 답변: "몽골에는 2017년에, 이탈리아는 2018년에 다녀오셨네요! 사진 보여드릴까요?"

**확장 시나리오 (R2~)**
- "결혼식 사진 좀 찾아줘" → 캡션·임베딩 의미 검색
- "그때 누구랑 갔어?" → Photos.app Persons 메타
- "케이크 먹은 사진" → 임베딩 의미 검색

---

## 3. 설계 결정 요약 (Decision Log)

| # | 결정 사항 | 선택 | 비고 |
|---|---|---|---|
| D1 | 사용자 범위 | 본인 1명 (개인 도구) | 멀티테넌시·인증 없음 |
| D2 | MVP 스코프 | 메타데이터 + Vision 캡션/임베딩 | 얼굴 인식은 자체 안 함 |
| D3 | Vision 처리 위치 | 전부 로컬 (M4 Pro 64GB) | bootstrap 환경으로 충분 |
| D4 | 사진 Source of Truth | iCloud/Photos Library 그대로, EDDR은 참조 | EDDR은 파생 데이터만 소유 |
| D5 | 답변 LLM | Claude API | 한국어 품질·tool use |
| D6 | Privacy 경계 | 텍스트(메타+캡션)만 API로, **이미지는 절대 전송 안 함** | 정밀 좌표·PII는 미전송 (ADR-0001) |
| D7 | UI 형태 | 로컬 Gradio 채팅 웹 UI | D25(FastAPI+React 채팅 SPA)를 거쳐 **D26(지도 중심 검색)으로 대체** |
| D8 | 인덱싱 사이클 | 1차 batch 후 점진적 업데이트 | content hash dedup · near-dup 그룹핑은 **ADR-0004로 v1 보류** |
| D9 | 동영상 | 제외 (사진만) | v2 후보 |
| D10 | 인물 데이터 | Photos.app Persons named만 import | photos_person_uuid 보존 · **person 질의는 ADR-0004로 폐기**(데이터 적재는 유지) |
| D11 | Trip 모델 | 자동 세그멘테이션 + `trips` 테이블 1등급 단위 | GPS + 시간 갭 기반 |
| D12 | iCloud Optimize 처리 | 인덱싱 시 on-demand 다운로드, 더티셔 유지 | macOS가 관리 |
| D13 | 완료 기준 | 골든셋 10문항 중 8개 이상 만족 | 손으로 작성 |
| D14 | Trip 정의 | **일상 반경 외 24h 이상**, 다국가도 1 trip (`trip_countries` M2M) | 1박 2일 trip도 인정 |
| D15 | Daily Radius | KDE 자동 클러스터링 → 사용자 setup wizard confirm·편집 | 다중 영역 (집/직장/본가) |
| D16 | Photo identity | Photos.app asset이 정체성 SoT (ADR-0002) | 원본+보정본 = 1 photo |
| D17 | iCloud Shared Library | 포함 (owner 무관) | 가족 추가 사진도 in scope |
| D18 | 인덱싱 제외 | hidden, burst non-keeper, screenshot, document scan, video, <300×300 | |
| D19 | Caption v1 | English 1개만, multilingual embedding이 한국어 query 처리 | 한국어 vLM 품질 risk 회피 |
| D20 | Embedding | 사진당 2개 (`image` + `caption_text`), single model | caption_text는 Chroma sidecar에 적재(ADR-0006). image leg는 후속 검증 |
| D21 | LLM tool surface | 5개 structured tools, freeform SQL 없음 (ADR-0003) | YAGNI |
| D22 | Indexing UX | Recent-first batch → background continue, status checkpoint | 첫 query 가능 시점 단축 |
| D23 | Golden set 구조 | R1:5/R2:3/R3:2, hybrid eval, 정답 형식 query별 혼합 | |
| D24 | 데이터 부재 보강 (user enrichment) | 검색 내부는 불변 — **날짜 기준 그룹 → 사용자 문답 → 파생 데이터 업데이트**로 보강 | G06(개심사)류 해소책(2026-06-11). **D26으로 흡수** — 수동 지오코딩(S4)·사진 메모(S5)가 이 결정의 구현 형태(wizard·채팅 문답은 미구현 폐기) |
| D25 | 웹 서비스화 | **자가호스팅 개인 웹 앱** — FastAPI+React SPA, Gradio(D7) 대체, 현 repo 모노레포 재구성 | 2026-06-11 확정. M1(API 서버)·M2(채팅 SPA) 구현 후 **UI 패러다임은 D26으로 교체** — 서버 인프라(ADR-0008)·SPA 자산은 계승 |
| D26 | 지도 중심 로컬 검색 전환 | **채팅 폐기·검색 전용** — 지도 홈(MapLibre+OpenFreeMap) + 자연어 검색(gemma4:e2b 해석, 외부 LLM 0회) + 수동 지오코딩(Nominatim /search·long-press) + 사진 메모(임베딩 합류) | 2026-06-11 사용자 확정 8건. [ADR-0009](adr/0009-map-local-search.md)(ADR-0003 supersede·ADR-0001 amend). SoT: [scenario.md](scenario.md)·[prd.md](prd.md) v2. taken_at KST 정규화 포함. 골든셋은 검색 결과 자동 채점으로 재정의 |

---

## 4. 데이터 모델

### 4.1 핵심 테이블

```
photos
  - id (uuid)
  - source ('photos_library' | 'google_takeout' | 'local')
  - source_uri (Photos UUID or 절대 경로)
  - content_hash (BLAKE3)
  - perceptual_hash (dHash 64bit)
  - taken_at (datetime)  -- D26(M1): KST(+09:00) aware ISO로 정규화 — "하루"=KST 달력일 (ADR-0009 §6)
  - taken_at_raw  -- D26(M1): 정규화 전 원본 보존
  - latitude, longitude  -- 로컬 거리계산·지도 렌더용; 외부 LLM 미전송, 내 브라우저 노출은 허용 (ADR-0001 + ADR-0009 §3)
  - country, city, district  -- reverse geocode 캐시
  - location_source  -- NULL=EXIF 유래 | 'manual'=수동 지정 (D26/ADR-0009 §4, M4)
  - width, height, camera_make, camera_model
  - trip_id (FK, nullable)
  - indexing_status ('meta_done' | 'missing_image' | 'caption_done' | 'skipped_video' | 'trip_assigned')  -- 현행 구현값
  - duplicate_of (FK photos.id, nullable)  -- cross-source dedup 마킹(§4.2); 질의 레이어는 duplicate_of IS NULL만 노출
  - near_duplicate_group_id (nullable)  -- v1 미사용(ADR-0004 보류)
  - created_at, updated_at

embeddings
  - photo_id (FK)
  - kind ('image' | 'caption_text' | 'note_text')  -- D20 두 종류 + D26(M5) 사용자 메모
  - model_id (ex: 'qwen3-embedding:8b')
  - vector_id (Chroma id)  -- 실제 벡터 payload는 Chroma sidecar에 저장 (ADR-0006)

captions
  - photo_id (FK)
  - model_id (ex: 'gemma4:e2b')
  - lang ('ko' | 'en')  -- v1엔 'en' 단일 (D19)
  - text
  - generated_at

notes  -- D26(M5): 사용자 메모 — 사진별 1건, Chroma eddr_note_text_v1로 임베딩
  - photo_id (PK, FK photos ON DELETE CASCADE)
  - text
  - updated_at

persons  -- v1: 데이터 적재만, 질의 폐기(ADR-0004)
  - id
  - photos_person_uuid  -- Photos.app person UUID (동명이인 구분)
  - name  -- Photos.app 라벨
  - photos_count

photo_persons (M2M)  -- v1: 데이터 적재만, 질의 폐기(ADR-0004)
  - photo_id, person_id

trips
  - id  -- 결정적: trip_<시작일 YYYYMMDD>_<NN> (구현 ⑥)
  - name (자동 생성: "이탈리아 여행 2018-04" — 해외=최빈 외국 국가명, 국내=최빈 city)
  - start_at, end_at  -- naive UTC 'YYYY-MM-DD HH:MM:SS' (구현 ⑥)
  - photo_count  -- 질의 레이어 노출 기준: 영상 미배정·duplicate_of IS NULL만 집계
  - center_lat, center_lng

trip_countries (M2M)
  - trip_id, country_code  -- 1 trip이 여러 country를 가질 수 있음 (D14)
    -- 구현(⑥, 2026-06-11): ISO 3166-1 alpha-2 대문자("KR"·"IT").
    --   geocode_cache.country_code(아래)에서 사진 좌표 셀 단위로 산출.
    --   한국어 국가명은 photos.country에 있으므로 여기엔 코드만 둔다(사용자 결정).

daily_radius_areas
  - id
  - label  -- "집", "직장", "본가" 등 사용자 라벨
  - center_lat, center_lng
  - radius_km

geocode_cache
  - lat_quantized, lng_quantized
  - country, city, district
  - country_code  -- ISO 3166-1 alpha-2 대문자 (⑥ 추가, trip_countries 산출용. ④분은 재조회 백필)
  - source ('nominatim')
  - fetched_at
```

### 4.2 dedup 규칙

- BLAKE3 일치 → 동일 파일, 한쪽만 인덱싱 (Photos Library 우선, D4)
  - 구현(④, 2026-06-10): 3소스가 이미 적재된 상태라 "적재 시 skip"이 아닌 **적재 후 일괄 마킹**으로 실현. content_hash 그룹에 소스가 2개 이상이면 canonical(photos_library > local > google_takeout, 동순위는 id 사전순) 외 행에 `duplicate_of` = canonical id를 기록. 데이터(캡션·임베딩)는 보존하고 질의 레이어(⑦)가 duplicate_of IS NULL만 노출. 같은 소스 내 동일 해시는 처리하지 않음(ADR-0002: dedup은 cross-source만).
- ~~BLAKE3 다름 + dHash 한 단위 차이 → `near_duplicate_group_id`로 묶음, UI는 그룹 당 1장 노출~~ → **v1 보류(ADR-0004)**: near-dup 미처리, 중복 허용

---

## 5. 인덱싱 파이프라인

```
[1] osxphotos로 Photos Library 메타 + 경로 + persons 추출
    └─ 필터: hidden / screenshot / document scan / <300×300 / burst non-keeper / video 제외 (D18)
       │
[2] 로컬 폴더 file scan
       │
[3] content_hash + perceptual_hash 계산 → dedup (cross-source만, near-duplicate 그룹화)
       │
[4] Optimize Mac Storage 사진은 on-demand 다운로드
       │
[5] 좌표 → reverse geocoding (OSM Nominatim, 캐시)
       │
[6] Daily Radius 추정 (KDE clustering top-N) → setup wizard에서 사용자 confirm·편집 (D15)
       │
[7] Vision: image embedding + 영어 caption + caption text embedding 생성 (로컬)
       │
[8] Trip 클러스터링 (Daily Radius 외 + 24h 이상 연속, 다국가는 1 trip 유지) (D14)
    -- 구현(⑥, 2026-06-11): `eddr trips recompute` 전체 재계산(멱등).
    --   run 분리는 복귀(일상 영역 내 사진)가 주 신호 + 안전장치 사진 공백 72h(파라미터).
    --   기간 내 no-GPS 사진도 배정(§8 "시간만 있으면 trip 포함"). 영상은 세그먼트
    --   입력·배정 모두 제외(사용자 결정 2026-06-11). caption_done만 trip_assigned 전이.
       │
[9] DB upsert
```

- **순서 (D22)**: Recent-first — 최근 1년치 우선 batch → query 즉시 가능 → 나머지 백그라운드
- **Checkpoint**: 각 단계마다 `photos.indexing_status` 갱신. 중단·재실행 시 status 기준 skip.
- **점진 사이클**: `eddr update`로 신규/변경 사진만 처리. `eddr update --recompute-trips`로 trip 재클러스터.

---

## 6. 질의 / 답변 흐름

```
사용자 입력 (한국어 자연어) — React SPA 지도 홈(MapLibre)의 하단 검색창
       │
       ▼
POST /api/search
  ├─ QueryExtractor (gemma4:e2b 로컬 — 구조화 추출: keywords_en·date_from/to·countries·cities,
  │                   실패 시 임베딩-only 폴백. 외부 LLM 호출 0회, ADR-0009 §2)
  ├─ 지역명 → trips 매칭 (trip_ids — GPS 무 사진도 장소 검색에 포함)
  └─ QueryService.semantic_search_photos (내부 검색 서비스, ADR-0009로 LLM tool 아님)
      ├─ 임베딩 leg: qwen3-embedding:8b + instruct prefix (원문 한국어 질의)
      ├─ lexical leg: FTS5 BM25 (영어 캡션 ← keywords_en)
      ├─ note leg: 사용자 메모 Chroma 컬렉션 (D26 M5)
      └─ RRF 융합 + adaptive over-fetch + 노출 필터(영상·dup 제외)
       │
       ▼
날짜별 lane (KST 달력일, 관련도순) + 지도 하이라이트 — 텍스트 답변 없음 (ADR-0009 §1)
```

**Privacy 보장 (ADR-0001 + ADR-0009 §3)**: 런타임 외부 LLM 호출 자체가 0회. 정밀 좌표는 "내 서버 → 내 브라우저"만 흐름(지도 렌더용 — ADR-0008 무인증 가드가 노출 경계). 외부 전송은 지도 타일 좌표(OpenFreeMap)·장소 검색어/지정 좌표(Nominatim, 서버 프록시)뿐. Photos hidden 사진은 인덱싱부터 제외. 이미지 바이너리는 절대 미전송.

**부분 인덱싱 UX**: 상태 배지 "N/M 검색 가능"(`GET /api/status`)으로 표시 — 채팅 footer 고지는 채팅 폐기로 소멸.

---

## 7. 기술 스택 (현재 합의)

| 영역 | 선택 | 비고 |
|---|---|---|
| 언어 | Python 3.11+ | |
| 사진 인입 | `osxphotos` + 자체 file scanner | |
| Vision (캡션) | gemma4:e2b (로컬) | Ollama. **프롬프트 P3_hybrid 확정**(03 EDA, D19 PASS recall@10 0.70). 현행 적재는 gemma4:e2b, 모델 A/B(Qwen3-VL vs gemma)는 ⑤ 골든셋 → [findings §8](01_eda_findings.md) |
| Vision (임베딩) | `qwen3-embedding:8b` caption_text 우선 | image leg는 SigLIP/CLIP/Qwen3-VL-Embedding 후속 검증 |
| DB | SQLite ledger + Chroma sidecar | SQLite는 원장/status, Chroma는 caption_text vector 검색 (ADR-0006) |
| Geocode (reverse + forward) | OSM Nominatim (자체 캐시·서버 프록시) | 무료, 1 req/s 준수. forward `/search`는 D26 M4 — 수동 위치 지정용 |
| Hashing | BLAKE3 + dHash | |
| UI | React SPA + MapLibre GL JS (OpenFreeMap 타일) | 지도 홈 + 검색 lane (D26). Gradio(D7)·채팅은 폐기 |
| 질의 해석 | gemma4:e2b (로컬 ollama) | 구조화 추출 — **런타임 외부 LLM API 0회** (D26/ADR-0009) |
| CLI | `typer` 또는 `click` | `eddr index`, `eddr update`, `eddr serve-api`, `eddr golden` |

---

## 8. Risk 및 대응 전략

| Risk | 1차 대응 | 2차 대응 |
|---|---|---|
| 로컬 vLM 한국어 캡션 품질 부족 | **v1엔 영어 caption 채택** (D19) | 한국어 사용 가능 시 lang='ko' 토글 |
| Photos.app Persons 라벨링 sparse | setup wizard 안내 ("Photos에서 라벨링하면 더 좋은 답") | 사용자 라벨링 UI 추가 (v2) |
| iCloud 다운로드 속도 병목 | 진행률·resume 지원 | 사전 일괄 다운로드 모드 안내 |
| 인덱싱 시간 (실측 ~9,054장 — 초기 "10만" 가정 11배 과대) | Recent-first + 백그라운드 (D22), status checkpoint | GPU/CPU 병렬화 튜닝 |
| EXIF 누락 사진 | 시간만 있으면 trip에는 포함, GPS 없으면 null | 사진의 폴더명·파일명으로 보조 추론 |
| Nominatim rate limit | 1 req/sec 준수 + 캐시 (lat/lng 양자화) | landmark 정밀도 필요 시 LLM 추론 보조 |
| 평가 부재 시 정체 | 골든셋 10문항 우선 작성 (D23) | 매 반복마다 골든셋으로 회귀 검증 |

---

## 9. 의도적으로 빠진 것 (v2 후보)

- 동영상 인덱싱
- 멀티유저 / 인증 / 클라우드 배포 — 멀티유저·인증은 D25([prd.md](prd.md)) M5로 이동, 클라우드 배포는 여전히 비포함(자가호스팅)
- 자체 얼굴 인식
- 영상 frame extraction
- 모바일 앱 — 네이티브는 비포함 유지, 모바일 접근은 D25 웹 반응형으로 해소
- 사용자가 답변 LLM에 이미지 직접 노출 (privacy 정책상 영구 제외 가능성)
- Photo edited variant 분리 보존
- 이사 등 일상 반경 변화 history
- Caption multi-language coexist (Korean + English)

---

## 10. 다음 액션

1. **골든셋 10문항 손으로 작성** (`docs/golden_set.yaml`)
   - 분포: R1 5 / R2 3 / R3 2 — R2(person)는 ADR-0004로 재정의 필요(TODO.md)
   - 정답 형식: query별 혼합 — fact-list (factual), photo_id list (person/semantic)
   - 평가: hybrid (factual = LLM judge 자동, semantic = 수동 spot-check)
2. 프로젝트 스켈레톤 (`pyproject.toml`, 디렉터리 구조, CLI entrypoint)
3. 인덱싱 파이프라인 1단계 — osxphotos 메타 추출 + 필터 + SQLite 저장
4. dedup + reverse geocoding + Daily Radius 추정 + setup wizard
5. Vision (caption + image embedding + caption text embedding)
6. Trip 클러스터링 (24h cutoff + 다국가 1 trip)
7. Gradio UI + Claude API + 5개 structured tool
8. 골든셋으로 회귀 검증 → 반복
9. **D26 지도 중심 검색 전환** — 마일스톤 M0~M6은 [prd.md §7](prd.md). ⑦의 Claude 경로·⑧-ⓑ(실 API 채점)는 ADR-0009로 재편·폐기, 골든셋은 검색 결과 자동 채점으로 전환

---

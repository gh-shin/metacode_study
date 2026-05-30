# EDDR (어디더라?) — MVP 설계서

> 그릴링 세션 결과 합의된 1차 설계. v1 구현 착수의 기준 문서.
> 작성일: 2026-05-28 (grilling 반영: 2026-05-29)
> 도메인 용어집은 [../CONTEXT.md](../CONTEXT.md), 핵심 결정은 [./adr/](./adr/) 참조.

---

## 0. 한 줄 요약

내 사진(약 10만 장) 메타데이터와 이미지 분석 결과를 로컬 DB로 만들고, 자연어 질문을 받으면 LLM이 "언제, 어디서, 누구랑, 뭘 했는지"를 알.잘.딱. 답해주는 개인용 로컬 챗봇.

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
| D7 | UI 형태 | 로컬 Gradio 채팅 웹 UI | 채팅 + 사진 그리드 |
| D8 | 인덱싱 사이클 | 1차 batch 후 점진적 업데이트 | content hash dedup |
| D9 | 동영상 | 제외 (사진만) | v2 후보 |
| D10 | 인물 데이터 | Photos.app Persons named만 import | photos_person_uuid 보존 |
| D11 | Trip 모델 | 자동 세그멘테이션 + `trips` 테이블 1등급 단위 | GPS + 시간 갭 기반 |
| D12 | iCloud Optimize 처리 | 인덱싱 시 on-demand 다운로드, 더티셔 유지 | macOS가 관리 |
| D13 | 완료 기준 | 골든셋 10문항 중 8개 이상 만족 | 손으로 작성 |
| D14 | Trip 정의 | **일상 반경 외 24h 이상**, 다국가도 1 trip (`trip_countries` M2M) | 1박 2일 trip도 인정 |
| D15 | Daily Radius | KDE 자동 클러스터링 → 사용자 setup wizard confirm·편집 | 다중 영역 (집/직장/본가) |
| D16 | Photo identity | Photos.app asset이 정체성 SoT (ADR-0002) | 원본+보정본 = 1 photo |
| D17 | iCloud Shared Library | 포함 (owner 무관) | 가족 추가 사진도 in scope |
| D18 | 인덱싱 제외 | hidden, burst non-keeper, screenshot, document scan, video, <300×300 | |
| D19 | Caption v1 | English 1개만, multilingual embedding이 한국어 query 처리 | 한국어 vLM 품질 risk 회피 |
| D20 | Embedding | 사진당 2개 (`image` + `caption_text`), single model | model upgrade 시 전체 재생성 |
| D21 | LLM tool surface | 5개 structured tools, freeform SQL 없음 (ADR-0003) | YAGNI |
| D22 | Indexing UX | Recent-first batch → background continue, status checkpoint | 첫 query 가능 시점 단축 |
| D23 | Golden set 구조 | R1:5/R2:3/R3:2, hybrid eval, 정답 형식 query별 혼합 | |

---

## 4. 데이터 모델

### 4.1 핵심 테이블

```
photos
  - id (uuid)
  - source ('photos_library' | 'local_fs')
  - source_uri (Photos UUID or 절대 경로)
  - content_hash (BLAKE3)
  - perceptual_hash (dHash 64bit)
  - taken_at (datetime)
  - latitude, longitude  -- 로컬 거리계산용; LLM 응답엔 미노출 (ADR-0001)
  - country, city, district  -- reverse geocode 캐시
  - width, height, camera_make, camera_model
  - trip_id (FK, nullable)
  - indexing_status ('pending' | 'meta_done' | 'embed_done' | 'caption_done' | 'trip_assigned')
  - near_duplicate_group_id (nullable)
  - created_at, updated_at

embeddings
  - photo_id (FK)
  - kind ('image' | 'caption_text')  -- 사진당 두 종류 보유 (D20)
  - model_id (ex: 'bge-m3')
  - vector (sqlite-vec)

captions
  - photo_id (FK)
  - model_id (ex: 'qwen2.5-vl-7b')
  - lang ('ko' | 'en')  -- v1엔 'en' 단일 (D19)
  - text
  - generated_at

persons
  - id
  - photos_person_uuid  -- Photos.app person UUID (동명이인 구분)
  - name  -- Photos.app 라벨
  - photos_count

photo_persons (M2M)
  - photo_id, person_id

trips
  - id
  - name (자동 생성: "이탈리아 여행 2018-04")
  - start_at, end_at
  - photo_count
  - center_lat, center_lng

trip_countries (M2M)
  - trip_id, country_code  -- 1 trip이 여러 country를 가질 수 있음 (D14)

daily_radius_areas
  - id
  - label  -- "집", "직장", "본가" 등 사용자 라벨
  - center_lat, center_lng
  - radius_km

geocode_cache
  - lat_quantized, lng_quantized
  - country, city, district
  - source ('nominatim')
  - fetched_at
```

### 4.2 dedup 규칙

- BLAKE3 일치 → 동일 파일, 한쪽만 인덱싱 (Photos Library 우선, D4)
- BLAKE3 다름 + dHash 한 단위 차이 → `near_duplicate_group_id`로 묶음, UI는 그룹 당 1장 노출

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
       │
[9] DB upsert
```

- **순서 (D22)**: Recent-first — 최근 1년치 우선 batch → query 즉시 가능 → 나머지 백그라운드
- **Checkpoint**: 각 단계마다 `photos.indexing_status` 갱신. 중단·재실행 시 status 기준 skip.
- **점진 사이클**: `eddr update`로 신규/변경 사진만 처리. `eddr update --recompute-trips`로 trip 재클러스터.

---

## 6. 질의 / 답변 흐름

```
사용자 입력 (한국어 자연어)
       │
       ▼
Gradio 채팅 UI
       │
       ▼
Claude API
  └─ tool use (ADR-0003 structured tools):
      ├─ search_photos(filters, limit=20)
      ├─ semantic_search_photos(query, k=20, filters)
      ├─ list_trips(filters, limit=10)
      ├─ get_trip(trip_id)
      └─ get_photo(photo_id)
       │
       ▼
LLM이 자연어 답변 생성 (한국어, 친근한 톤)
       │
       ▼
Gradio UI: 답변 텍스트 + 사진 그리드 (로컬 path로 직접 렌더)
```

**Privacy 보장 (ADR-0001)**: tool 응답 schema에 따라 정밀 좌표·PII EXIF 자동 미노출. Photos hidden 사진은 인덱싱부터 제외 → 자연 미노출. 이미지 바이너리는 절대 미전송.

**부분 인덱싱 UX**: 답변 footer에 "현재 N/M 사진 인덱싱됨" 표시. LLM이 인덱싱 미완료에 의한 부분 답일 가능성을 인지·반영.

---

## 7. 기술 스택 (현재 합의)

| 영역 | 선택 | 비고 |
|---|---|---|
| 언어 | Python 3.11+ | |
| 사진 인입 | `osxphotos` + 자체 file scanner | |
| Vision (캡션) | Qwen2.5-VL 7B (로컬) | Ollama 또는 vllm |
| Vision (임베딩) | BGE-M3 또는 SigLIP (multilingual) | image + caption text 동일 공간 |
| DB | SQLite + `sqlite-vec` | 단일 파일, 백업 용이 |
| Reverse geocode | OSM Nominatim (자체 캐시) | 무료, rate limit 주의 |
| Hashing | BLAKE3 + dHash | |
| UI | Gradio | 채팅 + 이미지 그리드 |
| 답변 LLM | Anthropic Claude API | tool use 활용 |
| CLI | `typer` 또는 `click` | `eddr index`, `eddr update`, `eddr serve` |

---

## 8. Risk 및 대응 전략

| Risk | 1차 대응 | 2차 대응 |
|---|---|---|
| 로컬 vLM 한국어 캡션 품질 부족 | **v1엔 영어 caption 채택** (D19) | 한국어 사용 가능 시 lang='ko' 토글 |
| Photos.app Persons 라벨링 sparse | setup wizard 안내 ("Photos에서 라벨링하면 더 좋은 답") | 사용자 라벨링 UI 추가 (v2) |
| iCloud 다운로드 속도 병목 | 진행률·resume 지원 | 사전 일괄 다운로드 모드 안내 |
| 10만 장 인덱싱 시간 | Recent-first + 백그라운드 (D22), status checkpoint | GPU/CPU 병렬화 튜닝 |
| EXIF 누락 사진 | 시간만 있으면 trip에는 포함, GPS 없으면 null | 사진의 폴더명·파일명으로 보조 추론 |
| Nominatim rate limit | 1 req/sec 준수 + 캐시 (lat/lng 양자화) | landmark 정밀도 필요 시 LLM 추론 보조 |
| 평가 부재 시 정체 | 골든셋 10문항 우선 작성 (D23) | 매 반복마다 골든셋으로 회귀 검증 |

---

## 9. 의도적으로 빠진 것 (v2 후보)

- 동영상 인덱싱
- 멀티유저 / 인증 / 클라우드 배포
- 자체 얼굴 인식
- 영상 frame extraction
- 모바일 앱
- 사용자가 답변 LLM에 이미지 직접 노출 (privacy 정책상 영구 제외 가능성)
- Photo edited variant 분리 보존
- 이사 등 일상 반경 변화 history
- Caption multi-language coexist (Korean + English)

---

## 10. 다음 액션

1. **골든셋 10문항 손으로 작성** (`docs/golden_set.yaml`)
   - 분포: R1 5 / R2 3 / R3 2
   - 정답 형식: query별 혼합 — fact-list (factual), photo_id list (person/semantic)
   - 평가: hybrid (factual = LLM judge 자동, semantic = 수동 spot-check)
2. 프로젝트 스켈레톤 (`pyproject.toml`, 디렉터리 구조, CLI entrypoint)
3. 인덱싱 파이프라인 1단계 — osxphotos 메타 추출 + 필터 + SQLite 저장
4. dedup + reverse geocoding + Daily Radius 추정 + setup wizard
5. Vision (caption + image embedding + caption text embedding)
6. Trip 클러스터링 (24h cutoff + 다국가 1 trip)
7. Gradio UI + Claude API + 5개 structured tool
8. 골든셋으로 회귀 검증 → 반복

---

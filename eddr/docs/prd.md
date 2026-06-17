# EDDR 웹 앱 PRD (v2) — D26 지도 중심 로컬 검색 전환

> 위상: **Source 레이어** — 웹 앱의 제품·아키텍처 권위 문서. 사용자 경험의 권위는 [`docs/scenario.md`](scenario.md)(v2).
> 근거: PLAN §3 **D26**(2026-06-11 사용자 확정) · [ADR-0009](adr/0009-map-local-search.md)(채팅 폐기·런타임 LLM 로컬화·좌표 로컬 노출 등 되돌리기 비싼 6건).
>
> **불변 선언 — ADR-0002(photo 정체성)·ADR-0008(서버 3계약)은 변경하지 않는다. ADR-0001은 ADR-0009로 보강(amend), ADR-0003은 superseded.** v1 PRD(D25, 채팅 중심)는 git 이력 보존 — M1(API 서버)·M2(SPA) 구현 자산은 본 v2가 계승한다.

## 1. 비전 · 문제 정의

**"질문 → 텍스트 답변"이 아니라 "질문 → 사진". 채팅앱이 아니라 지도 위의 내 기억.**

D25 M2(채팅 SPA)의 실사용 판정에서 드러난 한계 4가지:

1. **채팅이라는 형식 자체의 마찰** — 원하는 건 사진인데 텍스트 답변을 읽고 스크롤해야 함. 후속 질문 맥락도 실제론 거의 안 씀.
2. **공간 탐색 부재** — "여기 근처에서 찍은 사진"이 사진앱 기억의 1차 축인데 지도가 없음.
3. **외부 LLM 의존** — 질의마다 Claude API(비용·지연 수~수십 초·API 키·오프라인 불가)인데, 실질 기여는 질의 해석뿐(검색 코어는 이미 로컬).
4. **위치 미상 사진의 방치** — 노출 모집단 9,218 중 GPS 무 사진이 2,867장(31%) — 검색 필터·지도에서 영영 누락되는데 보강 동선이 없음(D24 인박스는 미구현 채 폐기).

## 2. 타깃 · 페르소나

[scenario.md §1](scenario.md). 사용자 1명(소유자 — 모바일 헤비) + 관람자(가족, 계정 없음). 멀티유저는 §6-e 전환 경로만.

## 3. 시나리오 요약

S1 지도 홈(현위치+마커) · S2 자연어 검색→날짜 lane(채팅 없음) · S3 더보기→날짜 상세(시트 축소·지도 확대) · S4 위치 미상 해소(빨간 느낌표→장소검색/long-press→일괄 지정) · S5 사진 메모(저장+임베딩) · S6 인덱싱 상태 · S7 모바일+Tailscale HTTPS · S8 가족 관람 · S9 멀티유저 스케치. 상세·수용 기준은 [scenario.md §3](scenario.md).

## 4. 사용자 확정 결정 (2026-06-11, D26-①~⑧ — 변경 시 사용자 재확정 필요)

| # | 결정 | 내용 |
|---|---|---|
| D26-① | 검색 엔진 = **완전 로컬** | 해석 gemma4:e2b(ollama, 캡션 모델 재사용) + 임베딩 qwen3-embedding:8b(색인과 동일 — 교체 불가). 외부 LLM API 0회 |
| D26-② | 장소 검색 = **Nominatim /search** | 서버 프록시·accept-language=ko·1 req/s. 한국 POI 약점은 long-press 직접 지정으로 보완 |
| D26-③ | **채팅 완전 제거** | ChatEngine·/api/chat·ChatPane·Gradio 삭제(git 복원 가능). ADR-0003 superseded |
| D26-④ | 현위치 = **Tailscale HTTPS** | `tailscale serve` — secure context 충족 + 원격 접속(구 M4) 동시 해결 |
| D26-⑤ | 골든셋 = **검색 결과 자동 채점** | 사진형=정답 사진 포함, fact형(G04·G08)=정답 날짜 lane 상위 노출. match 규칙 작성은 사용자. ⑧-ⓑ 실 Claude 채점 폐기 |
| D26-⑥ | 위치 미상 범위 = **전 그룹/2,867장 전체**(확정 시 실측 521그룹 → M1 KST 정규화로 날짜 경계 이동, M4 실측 525그룹) | 날짜 무 764장은 v1 제외(백로그) |
| D26-⑦ | lane 정렬 = **관련도순** | 그룹 내 최고 rank 순 |
| D26-⑧ | **taken_at KST 정규화 포함** | 기존 미결 타임존 TODO 승계 — "하루" = KST 달력일(ADR-0009 §6) |

구현 기본값(이견 시 변경 가능 수준): 지도 스택 MapLibre+OpenFreeMap(ADR-0009 §5) · 상태관리 zustand 1스토어 · 메모 검색은 임베딩 leg만 · 위치 일괄 지정은 날짜 그룹 단위 · 지도 라벨 기본 스타일 · 수동 지정 주소는 reverse 경로 통일(ADR-0009 §4).

## 5. 기능 요구사항 (FR) — phase(M) 단일 체계(v1 확정 ① 계승)

| FR | 내용 | 시나리오 | M |
|---|---|---|---|
| FR-MAP-1 | 지도 홈 — GPS 5,587점 GeoJSON 일괄 + 클러스터 + 고줌 썸네일 마커(상한 ~60) | S1 | M2 |
| FR-MAP-2 | 현위치 표시(watchPosition) — 거부/실패 시 최근 GPS 사진 위치 폴백 | S1·S7 | M2 |
| FR-MAP-3 | 날짜 상세 — by-date 전체 그리드 + 시트 축소 + 지도 fitBounds | S3 | M2 |
| FR-SEARCH-1 | 자연어 검색 → 날짜별 lane(접힘 5장·뷰포트 ~3장·'더보기'), 관련도순, 텍스트 답변 없음 | S2 | M3 |
| FR-SEARCH-2 | 질의 해석 — gemma4:e2b 구조화 추출(keywords_en·날짜·지역) + 해석 칩 + 임베딩-only 폴백 | S2 | M3 |
| FR-SEARCH-3 | 지역명→trips 매칭으로 GPS 무 사진 검색 포함(장소 OR 스코프) | S2 | M3 |
| FR-GEO-1 | 위치 미상 일별 그룹 드로어(빨간 배지·대표 썸네일 4·trip 힌트·진행 표시) | S4 | M4 |
| FR-GEO-2 | 장소 검색 — Nominatim /search 서버 프록시, 후보 ≤5 핀+flyTo | S4 | M4 |
| FR-GEO-3 | 위치 지정 — 후보 탭 또는 long-press → 확인 모달 → 날짜 그룹 일괄, `location_source='manual'` + reverse 주소 채움 | S4 | M4 |
| FR-NOTE-1 | 사진별 메모 1건 upsert/delete + 동기 임베딩(실패 시 embedded:false) | S5 | M5 |
| FR-NOTE-2 | 메모의 검색 합류 — note leg RRF 융합(임베딩-only) | S5 | M5 |
| FR-PHOTO-1~4 | (v1 계승) photo_id 썸네일 2단계 · 사진 상세(+좌표·메모 확장) · 원본 스트림 · 라이트박스 | S3·S8 | 완료+확장 |
| FR-STATUS-1 | (v1 계승) 인덱싱 상태 + path_health + **ollama 헬스 추가** | S6 | 완료·M6 |
| FR-DATA-1 | taken_at KST 정규화 백필(원본 보존) — 날짜 의미의 단일화 | S2·S3·S4 | M1 |

## 6. 신규 아키텍처

### 6-a. 모노레포 레이아웃 (v1 확정 ② 계승 + 변경분)

```
src/eddr/
  query/
    tools.py        # QueryService — 내부 검색 서비스로 재정의(ADR-0009). trip_ids·note leg 확장
    extract.py      # 신설(M3) — QueryExtractor: gemma4:e2b 구조화 추출
    golden.py       # 재작성(M3) — POST /api/search 경로 자동 채점
    engine.py · ollama_chat.py · app.py(Gradio)   # 삭제(M3)
  server/
    deps.py         # engine·chat_lock 제거 → extractor·note_store 주입
    routes/         # chat.py 삭제 · search.py·map.py·geocode.py 신설 · photos.py 확장
  geocode/
    nominatim.py    # search() 추가(reverse 동형 골격)
web/
  src/store.ts      # 신설 — zustand 1스토어(지도 카메라 요청 객체 패턴)
  src/features/map/ # 신설 — MapView·ThumbMarkers·useLongPress
  src/features/search/ · geocode/   # 신설. chat/ 삭제
```

pyproject: `maplibre-gl`·`zustand`는 web/package.json. **`anthropic`·`gradio` 제거**(M3), `ANTHROPIC_API_KEY` 요구 소멸.

### 6-b. API 표면 (전체)

| Method · Path | 요청 → 응답 | 비고 | M |
|---|---|---|---|
| `POST /api/search` | `{query}` → `{interpretation{keywords_en,date_from,date_to,countries,cities,fallback}, groups:[{date,place,photos:[{photo_id,taken_at,latitude,longitude,rank}]}], total}` | 서버 KST 날짜 그룹핑·관련도순. ollama 다운=503 한국어 detail | M3 |
| `GET /api/map/photos` | → GeoJSON FeatureCollection(properties: id·date) | 노출 GPS 전량 1회(gzip ~150-250KB), `Cache-Control: private, max-age=300`, 위치 지정 후 강제 재요청 | M2 |
| `GET /api/photos/by-date?date=` | → `{photos[]}`(좌표 포함, limit 500) | '더보기'·마커 탭 공용. KST 달력일 | M2 |
| `GET /api/photos/no-location` | → `{total_photos, groups:[{date,count,sample_photo_ids[≤4],trip_name?}]}` | 전 그룹 전량(M4 실측 525), date DESC | M4 |
| `GET /api/geocode/search?q=` | → `{candidates:[{name,latitude,longitude,type,address}]}` ≤5 | Nominatim 프록시(CORS·UA·1req/s 일원화) | M4 |
| `PUT /api/photos/location` | `{photo_ids[],latitude,longitude}` → `{updated,country,city,district}` | 일괄 1본(단건=ids 1개). reverse 경로 주소 채움 | M4 |
| `PUT /api/photos/{id}/note` | `{text}` → `{photo_id,text,embedded}` | upsert+동기 임베딩, 실패 시 embedded:false | M5 |
| `DELETE /api/photos/{id}/note` | → 204 | notes 행+벡터+embeddings 행 삭제 | M5 |
| `GET /api/photos/{id}` | 확장: +`latitude,longitude,location_source,note` | 좌표 로컬 노출(ADR-0009 §3) | M2·M5 |
| `GET /api/status` | 확장: +`ollama:{reachable,models[]}` | | M6 |
| 유지 | `/api/healthz` · `/api/photos/summary`(+좌표) · `thumb` · `original` · SPA 서빙 | ADR-0008 그대로 | — |
| **삭제** | `POST /api/chat` · `GET /api/chat/history` · `POST /api/chat/reset` | routes/chat.py 전체 | M3 |

### 6-c. 로컬 검색 파이프라인 (M3 핵심)

```
질의(한국어) ─→ QueryExtractor (gemma4:e2b, ollama structured output, temperature 0)
                 ├─ 프롬프트: 오늘 날짜(KST) 주입 + few-shot 4(시기/의미/복합/상대날짜)
                 ├─ 출력: {keywords_en[], date_from, date_to, countries[], cities[]}  ※ 지명은 한국어
                 └─ 폴백: JSON 실패 → 1회 재시도 → 임베딩-only(추출 전부 비움, fallback=true)
       ─→ countries/cities로 trips 조회 → trip_ids 확보 (GPS 무 사진 우회 — 구 Claude의 list_trips 역할 대체)
       ─→ QueryService.semantic_search_photos(query=원문, keywords=keywords_en, trip_ids, …)
            ├─ 임베딩 leg: qwen3-embedding:8b + instruct prefix (검증 자산)
            ├─ lexical leg: FTS5 BM25(영어 캡션 ← keywords_en)
            ├─ note leg(M5): Chroma eddr_note_text_v1 — 1-item leg의 rank 압축을 막기 위해
            │   메모 거리를 캡션 풀 거리 경쟁(가상 순위)으로 정규화해 vector leg에 병합 +
            │   note leg 이중 출현(합의 후보). 풀 탈락 메모는 기여 0 — 절대 컷오프 없음(§D-4)
            └─ RRF 융합(_rrf_fuse 가변 인자) + adaptive over-fetch + 노출 필터
       ─→ 서버 그룹핑: KST 날짜별, 그룹 정렬 = 그룹 내 최고 rank
```

- 장소 필터 의미론: `(country LIKE … OR city LIKE … OR trip_id IN …)` **단일 OR 그룹**(`PhotoQueryFilters.trip_ids` 신설). 임베딩 질의는 원문 한국어 유지(영어 변환 A/B는 백로그).
- 검색 라우트는 읽기 전용·무상태 — 구 chat_lock(전역 직렬화) 소멸. ollama 동시성은 ollama 큐에 위임.

### 6-d. 데이터 계약 변경

| 변경 | 내용 | hook 영향 |
|---|---|---|
| `photos.location_source TEXT` | NULL=EXIF 유래 · `'manual'`=수동 지정. `_migrate_photos_columns` 멱등 ALTER | **없음**(VALID_SOURCES·INDEXING_STATUSES 비변경) — 문서 4종 기재만 |
| `photos.taken_at` KST 정규화 | 진단(소스별 aware/naive 실측) → 규칙 사용자 확정 → 백필. 원본은 `taken_at_raw` 보존 + DB 사전 백업 | 없음 |
| `notes` 테이블 | `photo_id TEXT PK REFERENCES photos ON DELETE CASCADE, text, updated_at` — 사진별 1메모 | 없음 |
| `embeddings.kind='note_text'` | 기존 PK(photo_id,kind,model_id) 그대로 수용(D20 설계 계승) | 없음 |
| Chroma `eddr_note_text_v1` | 별도 컬렉션(캡션 컬렉션 재구축과 격리). 문서 측 instruct 없음·질의 측 prefix(캡션 규약 동일) | 없음 |

### 6-e. 멀티유저 전환 경로 (계승 + 쓰기 추가 반영)

- v1 "공짜 규율 3개" 유지: ① 전역 상태 `deps.py` 단일점 ② 절대경로 미노출 ③ 프론트 API 클라이언트 단일 모듈.
- v2 추가 규율: **웹의 쓰기는 위치 지정·메모 2종뿐** — 멀티유저 전환 시 이 두 경로만 소유자 검사를 끼우면 된다.

### 6-f. 삭제 체크리스트 (M3 일괄)

`src/eddr/query/engine.py` · `ollama_chat.py` · `app.py`(Gradio, v1 확정 ⑤의 이행) · `src/eddr/server/routes/chat.py` · `web/src/features/chat/`(M2에서 선삭제) · `deps.py` engine·chat_lock·transcript · `cli.py` `serve` 서브커맨드·`--backend/--model`(`--ollama-host` 유지) · pyproject `anthropic`·`gradio`(pyyaml 유지) · tests `test_engine.py`·`test_ollama_chat.py`·`test_app.py`·`test_api.py` 챗 부분. **유지**: `vision/prompt.py`(캡션 생성용) · `tools.py`(docstring 재정의) · `thumbnails.py` · FTS5 · 골든셋 yaml(v2 스키마 개정).

## 7. 마일스톤 — 각 단계 "동작하는 상태"

| M | 범위 | 동작하는 상태 (수용 기준) |
|---|---|---|
| **M0** 문서 개정 | scenario v2·prd v2·ADR-0009·PLAN·TODO·wiki 연쇄 | doc-contract hook 통과 + 사용자 문서 리뷰 승인 |
| **M1** KST 정규화 | taken_at 진단→규칙 확정(사용자 1회)→백필(원본 보존·백업) | 자정±2h 샘플 Photos 대조 일치 + 해외 trip 경계 수치 기록 |
| **M2** 지도 셸 | map/photos·by-date·좌표 노출, MapView+클러스터+썸네일 마커, App 셸 교체, tailscale serve 가이드 | **폰(tailnet HTTPS)에서 현위치→클러스터→날짜 상세→라이트박스→원본 저장** 무중단 |
| **M3** 로컬 검색 | extract.py·/api/search·trip_ids 스코프·lane UI + **채팅 일괄 삭제** + golden v2 | 골든셋 자동 채점 **G06 제외 9문항 중 8↑** + ollama kill→503 + pytest 클린. 외부 LLM 의존 0 달성 |
| **M4** 위치 미상 | no-location·geocode 프록시·location PUT·드로어→flyTo→long-press→모달 | 개심사 그룹 지정 → **G06 통과 = 10/10** + `location_source='manual'` DB 확인 |
| **M5** 메모 | notes·note 임베딩·RRF note leg·NoteEditor | 메모 단어 검색에 사진 포함 + **골든셋 10/10 무손상 회귀** |
| **M6** 운영(선택) | launchd·status ollama 헬스·실측 기록·wiki INGEST | 백로그 정리 완료 |

선검증 게이트(M3 착수 시): `scripts/bench_extract.py`로 골든 10 + 상대날짜 변형 ~10문항의 추출 JSON **사람 리뷰** — 프롬프트 확정 전 본격 코딩 금지.

## 8. 성공 지표

1. 골든셋 v2 자동 채점: M3 **8/9↑** → M4 **10/10** → M5 회귀 10/10
2. **런타임 외부 LLM API 호출 0회** (M3 — pyproject에서 anthropic 소멸로 구조 확인)
3. 검색 p95 < 8s(로컬, 콜드스타트 제외) · 지도 첫 페이로드 < 500KB · 썸네일 캐시 히트 p95 < 200ms(계승) · 1화면 < 1MB(계승)
4. 위치 미상 그룹 감소 추이(M4 실측 525 → 실사용 감소) — 빨간 배지가 동기 부여 장치
5. 주 3회 이상 모바일 접속(자기 측정, v1 계승)

## 9. 리스크

| 리스크 | 대응 |
|---|---|
| gemma4:e2b 추출 품질(상대날짜·지명) | bench_extract 선검증 + 임베딩-only 폴백 + 해석 칩 가시화 + 골든 자동채점 회귀 감시 |
| Nominatim 한국 POI 빈약 | 기대치 명문화(지명·역·사찰 양호, 상호 약함). **long-press 직접 지정이 항상 가능한 1급 경로** |
| 5,587 마커 성능 | supercluster 내장 + 썸네일 마커 고줌·상한 60 + 하이라이트 별도 source |
| 521그룹 수동 지정 피로 | 날짜 일괄 + trip 힌트 + 진행 표시. "전부 채우기"는 목표 아님 |
| KST 백필 사고 | 진단→사용자 확정→원본 보존+백업→경계 샘플 검증 절차 강제 |
| 타일·Nominatim 외부 의존 | ADR-0009 §3 수용 리스크 명문화. 오프라인 시 마커·검색은 동작(배경만 소실), PMTiles 백로그 |
| 무인증 서버의 좌표 서빙 | ADR-0008 가드 불변(루프백 기본·tailnet·공개 직노출 금지) |
| 번들 63KB→~300KB gzip | LAN/tailnet 전제 수용. 메인 화면이 지도라 코드 스플릿 무익 |

## 10. 부록

- **v1 확정 ①~⑥ 처치**: ①(phase 체계)·②(server 위치) 계승 / ③(SSE M3)·④(대화 영속화) **무효**(채팅 소멸) / ⑤(Gradio 삭제) M3에서 이행 / ⑥(ADR 시점) 패턴 계승 — ADR-0009를 착수 직전 작성.
- **구 마일스톤 대응**: v1 M1(API 서버)·M2(SPA) = 구현 자산 계승(TODO_ARCHIVE 기록 유지) · v1 M3(trips·enrichment·SSE) 폐기 · v1 M4(Tailscale) = 신 M2로 흡수 · v1 M5(멀티유저) = §6-e 유지.
- **용어**: 질의 노출 모집단 9,218(영상·dup 제외) · GPS 보유 5,587 · 위치 미상 2,867장/521일 그룹(날짜 무 764 별도) · 골든셋 G01–G10(`docs/golden_set.yaml` v2).

# ADR-0009: 지도 중심 로컬 검색 전환 — 채팅 폐기 · 런타임 LLM 로컬화 · 좌표 로컬 노출

## Status

Accepted (2026-06-11) — **supersedes ADR-0003**, **amends ADR-0001**

## Context

D25 M2(채팅 중심 React SPA)까지 구현 완료된 상태에서, 사용자가 실사용 관점의 UX 판정을 내렸다: **채팅 형식이 불편하다**. 원하는 것은 "질문 → 텍스트 답변"이 아니라 "질문 → 사진"이며, 메인 화면은 채팅창이 아니라 **지도**다(현위치 + 내 사진 마커). 2026-06-11 사용자 확정 8건:

1. 검색 엔진 = 완전 로컬(질의 해석은 소형 모델, 임베디드 환경 기동 지향)
2. 장소 검색(정방향 지오코딩) = Nominatim `/search`
3. 채팅 완전 제거
4. 현위치 = Tailscale HTTPS(LAN HTTP는 secure context 미충족 → `navigator.geolocation` 차단)
5. 골든셋 = 검색 결과 기반 자동 채점 전환
6. 위치 미상 워크플로 범위 = 노출 모집단 전체(실측 2,867장/521일 그룹; 날짜 무 764장은 v1 제외)
7. 검색 결과 날짜 lane 정렬 = 관련도순
8. `taken_at` KST 타임존 정규화를 본 전환 범위에 포함

이 중 **되돌리기 비싼 결정만** 본 ADR로 고정한다. 화면 구성·마일스톤 등 미세 설계의 권위는 `docs/prd.md`(v2)다.

핵심 긴장: 기존 아키텍처의 중심(ChatEngine + 5 tools, ADR-0003)이 "자연어 해석"을 외부 LLM(Claude) tool-use 루프에 위임했는데, 사진만 추천하는 UX에서 외부 LLM의 실질 기여는 **질의 1건의 구조화 해석**으로 축소된다. 한편 검색 코어(Chroma 시맨틱 + BM25 RRF 융합, 검증 norm 0.739)는 LLM 없이 동작한다.

## Decision

### 1. 대화형 UX 폐기 — 검색 전용 (ADR-0003 supersede)

- 채팅(질문→텍스트 답변→후속 질문 맥락)을 **제품에서 제거**한다. 질의의 출력은 사진(날짜별 lane)뿐이다.
- `ChatEngine`·Claude tool-use 루프·"LLM tool surface" 개념을 폐기한다. **ADR-0003은 superseded** — "정확히 5개 tool" 불변 규칙은 효력을 잃고, `QueryService`는 LLM 도구가 아닌 **내부 검색 서비스**로 존속한다(privacy 스키마·limit 강제 등 구현 자산은 계승).
- ADR-0003에 잔존하던 `persons?: [str]` 명세 불일치(ADR-0004가 유보한 정리 건)는 surface 자체의 소멸로 **함께 종결**된다.
- 골든셋 게이트는 "채팅 답변 채점"에서 **"검색 결과 자동 채점"**(사진형 = 정답 사진 포함, fact형 = 정답 날짜 lane 상위 노출)으로 재정의한다. 문항·match 규칙 작성은 골든셋 규약대로 사용자 몫.

### 2. 런타임 LLM 완전 로컬화 — 외부 LLM API 0회

- 질의 해석(한국어 → 영어 키워드 + 날짜 범위 + 지역명 구조화 추출)은 **`gemma4:e2b`**(ollama, 캡션 생성과 동일 모델 — 신규 의존 0)가 수행한다. 추출 실패 시 폴백은 임베딩-only 검색.
- 질의 임베딩은 색인과 동일한 **`qwen3-embedding:8b`** 유지 — 벡터 공간 정렬상 교체 불가.
- `anthropic` SDK·`ANTHROPIC_API_KEY` 요구를 제거한다. 런타임 외부 네트워크 의존은 **지도 타일 서버 + Nominatim 2개**가 전부다.
- TODO ⑧-ⓑ "2차 실 Claude API 채점"은 채점 대상(ChatEngine) 소멸로 **공식 폐기**.

### 3. 정밀 좌표의 로컬 노출 허용 (ADR-0001 amend)

- ADR-0001 경계의 본질을 명문화한다: 금지 대상은 **"외부 LLM API로의 전송"**이다. 정밀 좌표(`latitude`,`longitude`)의 **"내 서버 → 내 브라우저"** 전송은 지도 렌더링에 필수이며 허용한다 — ADR-0008 무인증 가드(기본 루프백·tailnet 권장·공개 직노출 금지)가 노출 범위의 경계다.
- 수용하는 신규 외부 의존 2건(둘 다 외부 LLM 아님, 최소 입자 원칙):
  - **지도 타일 서버(OpenFreeMap)** — 열람 영역의 타일 좌표가 노출됨. 오프라인화는 PMTiles 확장 경로 보유.
  - **Nominatim `/search`** — 사용자가 입력한 장소 검색어, 그리고 reverse 시 지정 좌표(기존 ADR-0001 수용 범위와 동일)가 전송됨. 서버 프록시 경유만 허용(브라우저 직접 호출 금지 — UA 식별·1 req/s 일원화).
- 이미지 바이너리 절대 미전송·hidden 제외·절대경로 미노출 등 나머지 조항은 전부 불변.

### 4. 수동 위치 지정 — DB 직접 갱신 + `location_source` 출처 구분

- 위치 미상 사진의 수동 지정은 `photos.latitude/longitude` **직접 갱신** + `photos.location_source = 'manual'`(기존 EXIF 유래 행은 NULL)로 기록한다. **원본 사진 파일은 비파괴**(EXIF 미수정) — D4(Photos가 SoT, EDDR은 파생 데이터만 소유)와 일관.
- 주소(country/city/district)는 forward 후보의 표기를 쓰지 않고 **기존 reverse geocode 경로(양자화 캐시 → Nominatim reverse)로 통일** — 기존 적재분과 행정구역 입자 일치, long-press(주소 없는 좌표) 경로와 단일화.

### 5. 지도 스택 — MapLibre GL JS + OpenFreeMap

- 렌더러 **MapLibre GL JS**, 타일 **OpenFreeMap**(키 불필요·무료 정책 명시). 근거: 클러스터링(supercluster) 내장·flyTo 내장·벡터 라벨(`name:ko`) 제어 가능·**PMTiles로 완전 오프라인 확장 경로**(임베디드 기동 지향과 정합). Leaflet 기각 — raster 공개 타일 정책·클러스터 플러그인 의존·오프라인 열위.

### 6. 날짜의 의미 = KST 달력일 — `taken_at` 정규화

- 날짜 lane·by-date·날짜 필터의 "하루"는 **KST(+09:00) 달력일**로 정의한다.
- 소스별 혼재(photos_library = 촬영지 offset aware · takeout = UTC aware · local = naive 로컬, `wiki/impl-log/trip-clustering.md` 실측)를 **KST aware ISO로 백필 정규화**한다. 원본 값은 보존 컬럼으로 유지, 변환 규칙은 진단 실측 후 확정(prd v2 M1).
- 해외 사진은 현지 달력일과 어긋날 수 있음을 수용한다(예: 이탈리아 저녁 사진 → KST 다음날). "내 기억의 타임라인은 한국 시간"이라는 단일 기준이 소스별 들쭉날쭉보다 낫다는 판단.

## Consequences

**Positive:**

- 런타임 외부 LLM 0회 — 비용 0·오프라인 동작(타일 제외)·API 키 관리 소멸. 검색 지연이 tool-use 루프(수~수십 초)에서 로컬 추출+검색(수 초)으로 단축.
- 검증된 검색 자산(RRF 융합·instruct prefix·adaptive over-fetch) 전부 계승 — 교체되는 것은 해석 레이어뿐.
- 좌표 로컬 노출로 지도·수동 지오코딩·향후 위치 기반 기능의 길이 열림.
- 수동 지정이 geocode 모집단을 늘려 장소 필터 검색의 커버리지가 실사용으로 개선되는 선순환.

**Negative / 수용한 리스크:**

- "작년 여름 제주" 해석 품질이 Claude → gemma4:e2b로 하락 가능 — 추출 벤치 선검증 + 임베딩-only 폴백 + UI 해석 칩(오추출 가시화)으로 흡수.
- 후속 질문 맥락("그때 게르 사진도 있어?") 상실 — 검색 전용 UX의 의도된 트레이드오프.
- 타일 서버에 열람 패턴 노출·Nominatim에 검색어 노출 — 최소 입자·프록시 일원화로 수용.
- 무인증 서버가 좌표를 서빙 — ADR-0008 가드 불변이 전제(공개 직노출 금지 재확인).
- KST 정규화 백필은 데이터 수술 — 원본 보존·사전 백업·경계 샘플 검증을 절차로 강제.

## 관련

- supersedes: **ADR-0003**(LLM tool surface — 개념 소멸) · amends: **ADR-0001**(privacy — 좌표 로컬 노출 조항 추가)
- 불변 계승: **ADR-0002**(photo 정체성) · **ADR-0008**(server 위치·photo_id 간접 서빙·무인증 가드)
- 상위 결정: **D26**(PLAN §3) · 설계 권위: `docs/scenario.md`(v2)·`docs/prd.md`(v2)
- 구현: `eddr serve-api` + `web/`(MapLibre SPA), `src/eddr/query/extract.py`(신규)

# Full-Dataset EDA — 설계 스펙

- **날짜**: 2026-06-03
- **상태**: approved (brainstorming) → 구현 계획 대기
- **산출물**: `notebooks/02_full_dataset_eda.ipynb`
- **관련 문서**: `docs/PLAN.md`, `docs/01_eda_findings.md`, `docs/adr/0004-eda-driven-scope-decisions.md`, `wiki/decisions/eda-scope.md`
- **선행 EDA**: `notebooks/01_eda.ipynb` (메타데이터 가정 검증, 9,047 assets 시점)

---

## 1. 목적 & 배경

`01_eda.ipynb`는 **데이터의 현재 상태를 이해하기 위한 insight 확보** 작업이었고(구현 게이트가 아님), 메타데이터 층은 전수로 충분히 파악됐다. 그러나 픽셀 층은 Photos 라이브러리의 로컬 보유분이 **2.7%(236장)** 뿐이라 미관측으로 남았다.

이후 사용자가 `data/local_photos/`에 **여행/이벤트별 고해상 아카이브(28GB·1,939파일)** 를 추가했고, iCloud 총량은 osxphotos 진단으로 **9,054 assets(100% iscloudasset, 95.8% 오프로드)** 로 확정됐다("~10만"은 약 11배 과대추정이었음).

**이번 세션 스코프**: 사진 자체 데이터(EXIF·파일·저비용 픽셀 파생값)에 기반한 insight + 두 소스 정합성 + **다음 세션 Ollama 분석용 근거 데이터 확보**. **Ollama(캡션/임베딩)는 이번 세션에 실행하지 않는다** — 분석 시간이 길어 다음 세션으로 분리.

---

## 2. 데이터 모델 (§1 셋업)

두 모집단:

| 이름 | 규모 | 성격 |
|---|---|---|
| `icloud_meta` | 9,054 assets | osxphotos PhotosDB, 메타데이터 전수, 픽셀 97.3% 오프로드 |
| `local_files` | **1,738** 분석가능 이미지 | `data/local_photos/` 재귀 walk |

**local_files 제외 대상**: PSB 4 · PSD 5 · ZIP 5 · 동영상(.mov/.mp4) — 분석가능 확장자는 `.jpg/.jpeg/.png/.heic/.heif`.

**수집 필드(파일당)**: `local_path`, `relative_folder`(예: `2019_이탈리아/day01`), `folder_top`(예: `2019_이탈리아`), `bytes`, EXIF(`DateTimeOriginal`, GPS 유무), 디코드 후 실해상도.

**매칭 키(local ↔ icloud)**: `original_filename` 정규화 + EXIF 촬영일시 근접.
- 정규화 규칙: basename, 대문자, 확장자 분리, 복사/편집 접미사 제거(` (1)`, `-1`, `_edited`, `_2` 등 패턴).
- 충돌(동일 정규화명 다중) 시 EXIF 촬영일시 근접으로 tiebreak.
- 결과는 **매칭 신뢰도 등급**(high: 파일명+날짜 일치 / medium: 파일명만 / none)으로 보고. 과대주장 금지.

---

## 3. 분석 항목

### §0. 폴더 분류 (folder taxonomy)
상위 폴더별 파일 수 + best-effort 파싱된 날짜/라벨 일람표. 아카이브 구조 자체를 한눈에 본다.
- `folder_date_hint`: 폴더명 앞자리 숫자에서 best-effort 추출(`181229`→2018-12-29, `2019`→2019). 취약하므로 힌트로만.
- `folder_top`(원문 그대로): "2019_이탈리아", "wedding" 등 — 장소명 정규화는 하지 않음(다음 세션 위임).

### §2. 정합성 분석 (reconciliation)
각 local_file을 icloud_meta에 매칭 → 3버킷:
- **overlap**: 오프로드된 iCloud 자산의 원본을 로컬에서 확보
- **iCloud-new**: iCloud에 없는 로컬 사진(진짜 풋프린트 확장) — 가설: `DSC_/DSCF_` 전용카메라 + PSD 편집본
- **iCloud-only**: 여전히 오프로드, 픽셀 없음

산출:
- 파일명 prefix(`IMG_` vs `DSC_/DSCF_` vs 기타) × 버킷 교차표 — 출처 가설 검증
- `folder_top` × 버킷 교차표
- **로컬 EXIF GPS/날짜 보유율** — 사용자 가설("로컬 파일 GPS 전무") 확인. 폴더명이 유일 위치 컨텍스트인 파일 규모 파악
- **보정된 총 사진 풋프린트** = 9,054 ∪ (iCloud-new) + 스케일 정정

### §3a. 실 해상도/품질
전수 1,738장 실제 W×H·메가픽셀·종횡비·포맷 분포. 매칭분은 osxphotos 메타 dim과 sanity 대조(편집본 리사이즈 탐지).

### §3b. 실 근접중복률 (D8 잠금 해제)
- BLAKE3 정확중복(byte-identical) 그룹
- dHash(`hash_size=8`, 64-bit) pairwise Hamming **전수 분포**(1,738² ≈ 1.5M쌍, numpy 벡터화 popcount)
- `(1)`/복사 접미사 아티팩트는 §1 정규화로 식별·배제(93샘플 오염 방지)
- `NEAR_DUP_CUTOFF=1` 적정성을 실분포로 검증
- **cross-folder 중복**(같은 사진이 여러 여행폴더에): 별도 집계
- → `01`에서 미측정으로 남았던 **실제 near-dup율**을 산출, ADR-0004 D8 재검토 근거 제공

### §3c. 비전-근거 데이터 확보 (전수 1,738장, **Ollama 미실행**)
같은 decode-once 패스에서 다음 세션 입력을 준비:
- **썸네일 export = 폴더 구조 미러링**: `data/local_photos/<rel>/<name>.<ext>` → `data/eda_cache/thumbs/<rel>/<name>.jpg`. 평탄화하지 않음(폴더 컨텍스트 보존).
  - 변환 규격: 긴 변 ≤ 1024px, JPEG q90, EXIF orientation 적용, HEIC→JPG.
- **vision 매니페스트** 생성(§9 스키마) — 다음 세션 Ollama가 즉시 소비.

---

## 4. decode-once 파이프라인 & 파일 크기 전략

사용자 제약("로컬 파일 1장당 용량이 큼", 28GB·최대 2.3GB)에 대응:
- **스트리밍**: 파일 1개씩 `read_bytes → BLAKE3 → PIL decode → (dHash + 실해상도 + 썸네일 저장) → close`. 28GB를 메모리에 적재하지 않음.
- **디코드 1회**: 해싱·해상도·썸네일이 단일 디코드를 공유.
- **거대/비이미지 제외**: PSB/PSD/ZIP/동영상.
- **캐시(parquet)**: 정합성·해시·매니페스트 → 재실행 저렴. 썸네일은 존재 시 skip.
- **예상 wall-clock**: HEIC 디코드 1,738장 ≈ 5–8분. 노트북에 실측 시간·캐시 크기 보고.

---

## 5. 산출물 / 핸드오프

- **노트북**: `notebooks/02_full_dataset_eda.ipynb` — 실사진 썸네일 임베드 → `01`과 동일하게 **gitignore**(프라이버시 ADR-0001).
- **findings 갱신**: `docs/01_eda_findings.md`(Source 권위)에 — 보정 풋프린트·iCloud-new율·**실 near-dup율**·실 해상도분포·출처분할·로컬 GPS 보유율 추가. 비전 brige 결과는 "다음 세션" 표기. 이후 `wiki/data-profile/eda-findings.md` 리프레시(AGENTS.md INGEST).
- **다음 세션 핸드오프 데이터**:
  - `data/eda_cache/thumbs/<폴더구조유지>/*.jpg`
  - `data/eda_cache/vision_manifest.parquet`
- **ADR로 flag(결정은 사용자, Claude 자동결정 금지)**:
  1. 스케일 정정(~10만 → 9,054 + 로컬 신규분)
  2. iCloud-new 사진의 D12(iCloud=SoT)·D16(Photos asset=identity) 영향
  3. 실 near-dup율 → D8 재검토
  - (D19/D20 비전 신뢰도는 다음 세션 결과 후)

---

## 6. 완료 기준
이 노트북이 다음을 답하면 완료:
1. 진짜 총 사진 풋프린트(+매칭 신뢰도)
2. 실 near-duplicate율(D8 근거)
3. 실 해상도/품질 분포
4. 출처 분할(`IMG_` vs `DSC_/DSCF_`)과 D12/D16 함의, 로컬 GPS 보유율
5. **다음 세션 Ollama용 근거 데이터(폴더구조 유지 썸네일 + 매니페스트) 준비 완료**

## 7. 에러 처리 & 재현성
- 열기/해싱/디코드 실패는 **flag 후 skip, crash 금지**(`01` 패턴 계승).
- `seed=42` 결정적.
- 모든 파일 I/O try/except 캡처, 실패 목록 표로 표시.

## 8. 비범위 (다음 세션)
- Ollama 캡션(gemma4:e2b)·임베딩(qwen3-embedding:8b) 실행
- 한국어 질의 → 영어 캡션 검색 brige 검증(D19/D20)
- image-embedding leg(SigLIP/CLIP)
- Trip 파라미터 민감도·no-GPS 시간근접 배정 심화(별도 후속)

## 9. vision_manifest.parquet 스키마 (1 row / local_file)

| 컬럼 | 설명 |
|---|---|
| `local_path` | 원본 절대/상대 경로 |
| `thumb_path` | 폴더구조 유지 썸네일 경로 |
| `filename_norm` | 정규화 파일명(매칭 키) |
| `relative_folder` | `data/local_photos` 기준 상대 폴더 |
| `folder_top` | 최상위 여행/이벤트 폴더(원문) |
| `folder_date_hint` | 폴더명 파싱 날짜(best-effort, nullable) |
| `exif_date` | EXIF DateTimeOriginal (nullable) |
| `has_exif_gps` | EXIF GPS 존재 여부 |
| `gps_lat`,`gps_lng` | 매칭된 iCloud 자산 좌표(있으면, nullable) |
| `matched_uuid` | 매칭된 iCloud asset uuid (nullable) |
| `match_confidence` | high / medium / none |
| `width`,`height` | 실 해상도 |
| `blake3` | 정확중복 키 |
| `dhash` | 근접중복 키(hex) |
| `bucket` | overlap / icloud_new / (해당없음) |

## 10. 가정 & 미해결
- local_photos 파일명이 원본 카메라 파일명을 보존한다고 가정(매칭 가능 전제). EXIF date로 보강하되, 리네임된 파일은 `match_confidence=none`으로 처리.
- `2509-10_아이슬란드` 등 일부 폴더 날짜 파싱은 모호 — 힌트로만, 원문 폴더 라벨이 1차 컨텍스트.
- 썸네일 1024px/q90이 다음 세션 비전 입력으로 충분하다고 가정(다음 세션에서 조정 가능).

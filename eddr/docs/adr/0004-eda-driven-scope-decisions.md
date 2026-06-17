# ADR-0004: EDA-Driven v1 Scope Decisions — near-dup 처리 보류 · Person 질의 폐기

## Status

Accepted (2026-05-31)

## Context

구현 착수 전, 실제 Photos Library(9,047 assets)로 설계 가정을 검증하는 EDA(`notebooks/01_eda.ipynb`)를 실행했다. 측정 결과는 [`docs/01_eda_findings.md`](../01_eda_findings.md)에 정리했다. 이 중 두 발견이 v1 범위 결정을 요구한다.

**near-dup (`D8`):** 디스크 샘플의 near-dup 93쌍은 전부 export 과정이 만든 `(1)` 복사본 아티팩트(BLAKE3·dHash 모두 동일, Hamming 0)였다. 라이브러리의 **실제 near-dup율은 미측정** 상태다. 또한 INDEXABLE의 로컬 파일 보유는 2.7%뿐이라(나머지 iCloud-only, 의도된 동작) 전체 해싱 기반 실측 자체가 별도 세션의 선행 작업을 필요로 한다.

검토한 옵션:

- (a) 지금 전체 라이브러리 해싱 + dHash cutoff 튜닝 강행 — 로컬 파일 2.7%뿐이라 실측 불가·불완전
- (b) v1에서 near-dup 처리를 보류하고 중복을 허용, 문제 발생 시 대응 — **채택**
- (c) near-dup 기능을 영구 폐기 — 추후 필요성이 불확실해 과도

**Person (`D10`):** named person이 라이브러리 전체에 **단 1명**, INDEXABLE의 **12.3%**(약 1,050장)에만 존재한다. R2(누구랑) person 질의의 recall이 데이터 차원에서 구조적으로 불가능하다.

검토한 옵션:

- (a) 계획대로 person 기반 질의(R2 3문항)를 유지 — named person 1명/12.3%로 recall 구조적 불가
- (b) person 기반 질의를 v1에서 폐기 — **채택**
- (c) 자동 unnamed face clustering으로 보완 — `D2`/`ADR-0002`가 unnamed face 제외를 규정, 범위 밖

## Decision

**`D8` — near-duplicate 처리 v1 보류:**

- 일단 duplication을 허용한다. 실제 문제(검색/그리드 중복 노출)가 발생하면 그때 대응한다.
- dedup 튜닝(dHash cutoff 등)은 로컬파일 기반 실측이 가능해진 뒤 **별도 세션**에서 결정한다.
- `near_duplicate_group_id` 등 dedup 산출물은 v1에서 미생성(또는 best-effort)한다.

**`D10` — Person 기반 질의(R2) v1 폐기:**

- named person 데이터 부족(1명 · 12.3%)으로 person 기반 질의를 v1 범위에서 제외한다.
- 인물 라벨이 충분히 축적되면 재검토한다.

두 결정 모두 데이터 여건 변화 시 재검토 가능한 **v1 한정** 결정이며, 영구 결정이 아니다.

## Consequences

**Positive:**

- 미검증·저가치 기능에 v1 구현 비용을 쓰지 않는다 (YAGNI, `ADR-0003` 정신과 일관).
- dedup cutoff는 실제 데이터로 정할 수 있을 때 결정 → 근거 없는 튜닝과 오분류를 회피.
- 범위 축소로 골든셋 R1·R3 품질에 역량을 집중할 수 있다.

**Negative:**

- near-dup 미처리 → 검색 결과·사진 그리드에 중복 사진이 노출될 수 있다.
- person 질의 폐기 → **골든셋 R2(3문항) 분포 재검토 필요(사용자 작업)**. 아울러 `persons`/`photo_persons` 테이블, `search_photos`의 person 필터, `ADR-0003`(LLM Tool Surface)의 재확인이 필요하다(본 ADR은 영향만 flag하며 실제 수정은 별도 결정).
- 위 두 결정은 v1 한정이므로, 데이터 여건이 바뀌면(인물 라벨 증가, dedup 구현) 다시 열어 검토해야 한다.

## 후속 EDA 보강 (2026-06-04)

01 이후 02·03 EDA가 본 결정의 **근거를 보강**했다(결정 자체는 불변).

- **D8 (near-dup 보류) — 실측으로 뒷받침**: 01 시점 "라이브러리 실제 near-dup율 미측정" 빈칸을, 02(`notebooks/02_full_dataset_eda.ipynb`)가 사용자 로컬 아카이브 1,738장으로 처음 측정 → **dHash Hamming≤1 919쌍(전체 쌍의 0.061%)**, BLAKE3 정확중복 14파일, cross-folder 334쌍(36.3%, 여행 백업 패턴). **0.061%는 낮아 v1 보류 유지가 타당**함을 확인. cutoff·처리 여부는 여전히 인덱싱 후 재튜닝 대상. → [`docs/01_eda_findings.md §7.5`](../01_eda_findings.md)
- **D10 (person 질의 폐기) — 변화 없음**: 02·03에서 person 데이터 변동 없음. 결정 유지.
- **(참고) 03 Vision EDA**: 본 ADR(D8/D10) 범위 밖이나 같은 EDA-driven 맥락의 후속 결정. **D19(영어 캡션 + multilingual 임베딩)이 한국어 질의 검색에서 PASS**(recall@10 0.70), 캡션 프롬프트 **P3_hybrid 확정**(사용자 2026-06-04). 캡션검색이 *지명 질의에 약함*(제주·일산 recall 0)이 측정돼, **D14(trip)·geocode 기반 메타 검색의 필요성이 실측으로 정당화**됨. 상세 [`docs/01_eda_findings.md §8`](../01_eda_findings.md).

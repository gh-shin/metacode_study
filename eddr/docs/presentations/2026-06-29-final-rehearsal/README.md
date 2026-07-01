# EDDR Final Rehearsal Presentation

작성일: 2026-06-29

최종 리허설 발표용 정적 HTML 덱이다. 목적은 EDDR 프로젝트 전반을 제품 시나리오, 로컬 검색 구조, 검색 품질 실험, 운영 후보 결정까지 한 흐름으로 설명하는 것이다.

## 열기

```bash
open docs/presentations/2026-06-29-final-rehearsal/index.html
```

키보드 조작:

- `←` / `→`: 이전·다음 슬라이드
- `PageUp` / `PageDown`: 이전·다음 슬라이드
- `Space`: 다음 슬라이드
- `P`: 인쇄 또는 PDF 저장

## 구성 원칙

- 날짜순이 아니라 factor가 적은 검색 실험에서 factor가 많은 실험으로 이동한다.
- 발표 흐름은 문제, 제품, 사용자 시나리오, 구조, 데이터, 실험 matrix, 통계 해석, 운영 결정, 데모 스크립트 순서다.
- 기존 데모 스크린샷은 `../2026-06-25-project-presentation/img/`를 참조한다.
- 최신 검색 결론은 `docs/work/2026-06-28-intent-policy-engine/final-report.md`와 `reports/rag_quality/ASSIGNMENT_REPORT.md` 기준이다.

## 핵심 메시지

```text
EDDR = 개인 사진을 로컬에 색인하고,
       한국어 질문을 지도·날짜·사진 탐색으로 바꾸는 앱.

검색 운영 후보 = A0/P0
  - SLM QueryExtractor 유지
  - extracted keyword boost off
  - k=20 dense/forced-precision 경로
  - A8, Phase B, no-SLM은 불채택
```

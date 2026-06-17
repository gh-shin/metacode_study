# 포스트모템 — 캡션 품질 개선 및 음식 재캡션 (2026-06-14)

> blameless 회고. 객관적·학습 중심으로 기록한다. 개인 지적·변명은 배제하고
> "무엇을 배웠고 무엇을 바꿀지"에 초점.

## 1. 개요

"냉면" 검색에 콩나물·숙주 사진이 섞이는 오염을 계기로 캡션 품질을 개선했다.
평가로 원인이 **프롬프트가 아니라 비전 모델 체급**임을 규명하고, 음식 1,393장을
투트랙(로컬 `qwen3-vl:8b` + 원격 macmini `gemma4:31b`, 프롬프트 `p5_grounded`)으로
재캡션했다. 진행 중 **ChromaDB 멀티스레드 데드락**과 **mlx 비전 미지원**이라는 두
인프라 이슈를 겪었으나, 캡션·색인 분리와 GGUF 복구로 해결하고 콩나물 오염을
해소했다. 최종적으로 master에 병합(`292c588`).

## 2. 타임라인 (대략, KST)

- **06-13 오전** — 골든셋 평가 중 "냉면"→콩나물 오염 발견. `eddr search audit`으로
  `gemma4:e2b`가 콩나물을 `noodles`로 오캡션하고 그 텍스트가 검색으로 증폭됨을 확인.
- **06-13 오후** — 범용 26장 절대품질 평가(Opus가 사진 직접 대조 채점). "모델 체급"이
  원인임을 입증(gemma4:e2b 7.1 / 치명결함 4 vs qwen8b·gemma31b 9.4+/0). `p4`·`p5_grounded`
  프롬프트 추가.
- **06-13 밤~06-14 새벽** — 투트랙 재캡션 시작. **712장 후 hang(1차)**. ollama timeout
  부재로 오진·수정. 재시작 후 **326장에서 또 hang(2차)**.
- **06-14** — `sample` 스택으로 hang 원인이 **ChromaDB rust binding 데드락**임을 확정.
  단일 스레드 안전성 측정(200건 58초 무사고) → **캡션·Chroma 분리** 구현. mlx 전환
  시도 → **550장 환각 발견** → 롤백 → `gemma4:31b`(GGUF) 복구. reindex 후 냉면 검색
  오염 해소 확인 → master 병합.

## 3. 근본 원인 분석

| 이슈 | 표면 증상 | 근본 원인 |
|---|---|---|
| 검색 오염 | 냉면 검색에 콩나물 | production 기본 `gemma4:e2b`가 콩나물·떡을 noodle로 오캡션(모델 용량 한계, 프롬프트로 교정 불가). 오캡션 텍스트가 임베딩·FTS·RRF로 증폭 |
| hang ×2 | 재캡션이 수백 장 후 정지 | `chromadb` 1.5.9 rust binding이 **ollama 워커 스레드 + 메인 Chroma upsert 동시 실행** 시 누적 ~300건 후 `_pthread_cond_wait` 데드락. 단일 스레드는 안전 |
| mlx 환각 | 캡션 550장이 2종류 텍스트 | ollama `gemma4:31b-mlx`가 **이미지 입력을 처리하지 못함**(텍스트 전용 동작) → 사진 무시하고 환각 |

## 4. 영향 범위

- **사용자(단일 사용자)**: 음식 검색 정확도 저하(오염). 개선 후 해소.
- **작업 시간**: hang 2회로 캡션 ~1,000장 분량 재작업, mlx 550장 폐기·롤백. 누적 수 시간 지연.
- **데이터**: mlx 임베딩으로 Chroma 일시 오염 → reindex로 회복. `captions`는 `(photo_id,
  model_id, lang)` 멱등·공존 구조라 영구 손실 없음. production 코드·스키마 변경 없음.

## 5. 대응 및 해결

- **hang**: 프로세스 종료 → `sample`로 스택 진단 → 단일 스레드 측정 → **캡션 생성(투트랙
  워커)과 Chroma 색인(단일 스레드)을 시간 분리**. `vision recaption --no-vector`(캡션만)
  + `vision reindex-vectors`(단일 스레드 색인) 신설.
- **mlx**: distinct=2(550장 중 고유 텍스트 2개)로 환각 확정 → 해당 캡션 삭제·롤백 →
  검증된 GGUF `gemma4:31b`로 복구(distinct 992/995로 정상 확인).
- **검증**: 콩나물 케이스가 "noodles"→"bean sprouts/rice"로 정정, 냉면 검색 top-10에서
  콩나물 제거·실제 면/냉면 노출 확인.

## 6. 재발 방지

1. **ChromaDB는 단일 스레드 색인으로 분리** — 멀티스레드 동시 upsert 금지. `--no-vector`
   + `reindex-vectors` 패턴을 표준으로(전량 재캡션에도 재사용).
2. **새 모델 검증은 출력 내용까지** — 실행 성공(`processed`/`failed`)이 아니라 distinct·
   이미지 반영을 확인. 특히 비전 모델은 "서로 다른 사진이 다른 캡션을 받는가".
3. **외부 호출에 timeout** — ollama 클라이언트 600s(무한 hang 차단). host=None 로컬
   경로도 포함.
4. **교훈을 메모리에 영속화** — `chromadb-multithread-deadlock`, `ollama-mlx-no-vision`.

## 7. 교훈 (배운 점)

- **검증의 위치가 핵심**: 모델은 "돌았나"가 아니라 "이미지를 봤나(distinct)", 인프라는
  "코드가 맞나"가 아니라 "런타임에 hang하나"로 검증해야 한다. 두 이슈 모두 이 지점을
  건너뛰어 발생했다.
- **분리 설계**: 무거운 병렬(캡션 생성)과 취약한 직렬(Chroma)을 분리하면 둘 다 안전해진다.
- **추측보다 측정**: 1차 hang을 ollama timeout으로 오진했으나 `sample` 스택으로 정정.
  데드락 가설도 단일 스레드 200건 측정으로 확정한 뒤 설계했다.
- **측정 우선 의사결정**: "모델 체급" 가설을 26장 채점으로 입증한 뒤 재캡션에 착수해,
  방향을 데이터로 확정했다.

## 부록: 산출물·커밋

- **코드(master 병합 `292c588`)**: `p4_grounded`·`p5_grounded` 프롬프트,
  `run_caption_text_batch_routed_dual`(도메인 라우팅 투트랙), `vision recaption --no-vector`,
  `vision reindex-vectors`(단일 스레드 색인), ollama timeout.
- **산출물**: `reports/caption_audit/`(26장 평가·점수·보고서, 음식 재캡션 foodset),
  `wiki/impl-log/caption-quality-audit.md`.
- **남은 과제**: ① 메뉴·포스터 등 "텍스트 속 음식명" false positive 검색 정책,
  ② 비음식(인물·풍경·문서) 재캡션(분리 파이프라인으로 동일 확장 가능).

# ADR-0007: 로컬 Vision의 LAN 분산 — 사용자 소유 사설 노드

## Status

Accepted (2026-06-08)

## Context

D3은 "Vision 처리 = 전부 로컬(M4 Pro 64GB)"으로 정했다. 빌드 ⑤ 본 caption run에서 실측 처리율이 **caption 10.5s/장**(embed 0.3s)으로, 전량 11,639장 단일 서버 ETA가 ~34h(파일럿 관측 ~56h)였다. caption 추론이 GPU-bound 단일 병목이라 한 머신에서는 더 줄일 여지가 없다.

사용자 홈 네트워크에 2번째 Ollama 노드(`192.168.0.56`, gemma4:e2b 동일)가 있고, 벤치마크상 원격 GPU가 로컬보다 빠르다(synthetic warm 5.7s vs 8.0s). caption을 두 노드에 분산하면 ETA ~14h로 단축된다.

이때 **사진 원본(이미지 바이너리)이 이 머신을 떠나 LAN 노드로 전송**된다. ADR-0001/D6의 불변규칙은 "외부 LLM API(Anthropic 등 클라우드)로 이미지 미전송"이며, LAN 노드의 로컬 Ollama는 클라우드 LLM이 아니라 **사용자 소유 로컬 vision 인프라**다. 따라서 D6의 경계(클라우드 LLM)는 침범하지 않으나, D3가 암묵 가정한 "단일 머신"을 확장하는 새 결정이 필요하다.

## Decision

로컬 vision(caption) 추론을 **사용자 소유 사설 LAN Ollama 노드**로 분산하는 것을 허용한다.

조건(불변):

- 대상 노드는 **사용자 소유 사설망 내**(RFC1918 홈 LAN 또는 사용자 tailnet)여야 한다. 인터넷·제3자 호스팅 노드 금지.
- **embedding은 단일 노드(로컬)로 고정** — 두 노드의 "동일" 모델이라도 양자화/버전 미세차로 벡터공간이 드리프트할 수 있어, 한 Chroma 컬렉션의 일관성을 위해 embed는 분산하지 않는다.
- DB·Chroma 쓰기는 **단일 writer**(로컬 메인 스레드).
- ADR-0001/D6은 그대로 유지 — **클라우드 LLM(Anthropic)로는 여전히 이미지 미전송**.

## Consequences

**Positive:**

- 전량 caption ETA ~34h → ~14h (2노드, 원격이 더 빠름).
- 설계상 N-worker라 노드 추가 시 선형 확장 가능.

**Negative / 수용한 리스크:**

- 이미지가 **평문 HTTP**로 사설 LAN을 흐른다(Ollama 기본 비암호화). 사용자 신뢰 홈 LAN 한정 전제로 수용 — 공용·비신뢰 네트워크 사용 금지.
- ETA가 원격 노드 가용성에 의존. 노드가 빠지면 단일 서버로 폴백(`--remote-host` 생략).
- v2 multi-user/cloud 배포 시 D6와 함께 재검토.

## 관련

- 확장 대상: **D3**(Vision 처리 위치) · 불변 유지: **ADR-0001 / D6**(외부 LLM 경계)
- 구현: `eddr vision run --remote-host <url>`, `run_caption_text_batch_dual` (caption 2노드 분산 / embed·persist 로컬 단일 writer)

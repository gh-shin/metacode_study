---
title: "로컬 Vision의 LAN 분산"
source: ["docs/adr/0007-lan-distributed-vision.md"]
last_verified: 2026-06-08
status: fresh
confidence: high
tags: [vision, privacy, performance, ollama]
---

## 결정 요약

로컬 caption 추론을 **사용자 소유 사설 LAN Ollama 노드**로 분산 허용 (ADR-0007). D3("Vision 전부 로컬")의 단일 머신 가정을 사설 LAN으로 확장. ADR-0001/D6(클라우드 LLM로 이미지 미전송)은 **불변 유지** — LAN 노드는 클라우드가 아니라 사용자 로컬 vision 인프라.

## 왜

빌드 ⑤ 실측: caption **10.5s/장**이 GPU-bound 단일 병목(embed 0.3s). 전량 11,639장 단일 서버 ~34h(파일럿 ~56h). 2번째 노드(`192.168.0.56`, 원격 GPU가 더 빠름)에 caption 분산 → **~14h**.

## 불변 조건

- 대상 노드 = 사용자 소유 사설망(홈 LAN/tailnet). 인터넷·제3자 금지.
- **embed는 로컬 단일 노드 고정** — 벡터공간 드리프트 방지(한 Chroma 컬렉션 일관성).
- DB·Chroma는 단일 writer(로컬 메인 스레드). caption만 멀티노드 동시.
- 클라우드 LLM(Anthropic)로는 이미지 여전히 미전송.

## 리스크 (수용)

- 평문 HTTP로 이미지가 사설 LAN을 흐름 → 신뢰 홈 LAN 한정.
- 원격 노드 빠지면 단일 서버 폴백(`--remote-host` 생략).

## 구현

`eddr vision run --remote-host http://192.168.0.56:11434` → `run_caption_text_batch_dual` (caption 2노드 thread 분산 / embed·persist 로컬). → [batch.py](../../src/eddr/vision/batch.py)

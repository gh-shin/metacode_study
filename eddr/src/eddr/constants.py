"""EDDR 프로젝트 공통 상수 — 모델명 등 전역 리터럴을 중앙화한다.

이 모듈은 순수 상수만 담으며 외부 의존성이 없다.
"""

EXTRACT_MODEL: str = "gemma4:e2b"
"""질의 추출 모델 (ollama structured output, temperature 0)."""

CAPTION_MODEL: str = "gemma4:e2b"
"""기본 캡션 생성 모델."""

EMBEDDING_MODEL: str = "qwen3-embedding:8b"
"""캡션 텍스트 임베딩 모델."""

DOC_RECAPTION_MODEL: str = "qwen3-vl:8b"
"""문서/포스터 strand 재캡션 모델 (로컬 OCR 우위)."""

NONDOC_RECAPTION_MODEL: str = "gemma4:31b"
"""비문서 strand 재캡션 모델."""

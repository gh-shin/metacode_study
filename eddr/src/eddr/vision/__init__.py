"""eddr.vision 패키지 — Ollama 기반 사진 캡션·임베딩 파이프라인."""

from eddr.vision.batch import VisionBatchReport, run_caption_text_batch
from eddr.vision.ollama_client import OllamaVisionClient
from eddr.vision.prompt import P3_HYBRID_PROMPT_NAME, P3_HYBRID_V2_PROMPT_NAME

__all__ = [
    "OllamaVisionClient",
    "P3_HYBRID_PROMPT_NAME",
    "P3_HYBRID_V2_PROMPT_NAME",
    "VisionBatchReport",
    "run_caption_text_batch",
]

"""검색 실험용 caption reranker factory."""

from __future__ import annotations

from typing import Literal

from eddr.query.tools import CaptionReranker

RerankerKind = Literal["none", "cross_encoder", "flashrank"]
_CROSS_ENCODER_MODEL = "BAAI/bge-reranker-v2-m3"
_FLASHRANK_MODEL = "ms-marco-MultiBERT-L-12"


class _CrossEncoderReranker:
    """sentence-transformers CrossEncoder adapter."""

    def __init__(self, model_name: str = _CROSS_ENCODER_MODEL):
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model_name)

    def score(self, query: str, captions: list[str]) -> list[float]:
        pairs = [(query, caption) for caption in captions]
        return [float(score) for score in self.model.predict(pairs)]


class _FlashRankReranker:
    """FlashRank adapter that returns scores in the original caption order."""

    def __init__(self, model_name: str = _FLASHRANK_MODEL):
        from flashrank import Ranker, RerankRequest

        self.model = Ranker(model_name=model_name)
        self.request_type = RerankRequest

    def score(self, query: str, captions: list[str]) -> list[float]:
        passages = [{"id": str(idx), "text": caption} for idx, caption in enumerate(captions)]
        results = self.model.rerank(self.request_type(query=query, passages=passages))
        fallback_scores = {
            str(item.get("id")): float(len(results) - rank)
            for rank, item in enumerate(results)
            if "id" in item
        }
        scores = {
            str(item.get("id")): float(item.get("score", fallback_scores[str(item.get("id"))]))
            for item in results
            if "id" in item
        }
        return [scores.get(str(idx), 0.0) for idx in range(len(captions))]


def build_reranker(kind: str | None) -> CaptionReranker | None:
    """reranker 이름을 QueryService가 쓰는 score 프로토콜로 조립한다."""
    match (kind or "none").strip() or "none":
        case "none":
            return None
        case "cross_encoder":
            return _CrossEncoderReranker()
        case "flashrank":
            return _FlashRankReranker()
        case unknown:
            raise ValueError(f"unknown reranker: {unknown}")

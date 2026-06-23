"""검색 실험 하네스 변형 설정."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExpansionKind = Literal["none", "multiquery", "hyde"]
RerankKind = Literal["none", "cross_encoder", "flashrank"]


@dataclass(frozen=True)
class RetrievalConfig:
    """검색 실험 변형 하나의 capability 스위치."""

    expansion: ExpansionKind = "none"
    rerank: RerankKind = "none"


VARIANTS: dict[str, RetrievalConfig] = {
    "baseline": RetrievalConfig(),
    "rerank_ce": RetrievalConfig(rerank="cross_encoder"),
    "rerank_flash": RetrievalConfig(rerank="flashrank"),
    "multiquery": RetrievalConfig(expansion="multiquery"),
    "hyde": RetrievalConfig(expansion="hyde"),
    "full": RetrievalConfig(expansion="multiquery", rerank="cross_encoder"),
}


def get_retrieval_config(name: str | None) -> RetrievalConfig:
    """변형 이름을 설정으로 해석한다. 빈 값은 baseline이다."""
    key = (name or "baseline").strip() or "baseline"
    try:
        return VARIANTS[key]
    except KeyError as exc:
        known = ", ".join(sorted(VARIANTS))
        raise ValueError(f"unknown retrieval variant: {key} (known: {known})") from exc

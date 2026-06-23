"""LangChain 기반 검색 질의 확장."""

from __future__ import annotations

import re
from typing import Literal

ExpansionKind = Literal["none", "multiquery", "hyde"]
_EXPANSION_MODEL = "gemma4:e2b"
_LINE_PREFIX_RE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s*")


class LangChainQueryExpander:
    """LangChain LCEL chain으로 질의 변형을 생성한다."""

    def __init__(
        self,
        kind: ExpansionKind,
        *,
        chain=None,
        expansion_n: int = 3,
        ollama_host: str | None = None,
    ):
        """생성 모드와 LangChain chain을 보관한다."""
        if kind not in {"multiquery", "hyde"}:
            raise ValueError(f"unknown expansion: {kind}")
        self.kind = kind
        self.expansion_n = expansion_n
        self.chain = chain or _build_langchain_chain(kind, expansion_n, ollama_host)

    def expand(self, query: str) -> list[str]:
        """원 질의와 LangChain 생성 질의를 중복 제거해 반환한다."""
        text = self.chain.invoke({"query": query, "n": self.expansion_n})
        if self.kind == "hyde":
            return _dedupe([query, _coerce_text(text)])
        return _dedupe([query, *_parse_lines(_coerce_text(text))])[: self.expansion_n + 1]


def build_query_expander(
    kind: str | None, *, ollama_host: str | None = None
) -> LangChainQueryExpander | None:
    """검색 변형 이름을 expander로 조립한다. none이면 비활성이다."""
    key = (kind or "none").strip() or "none"
    if key == "none":
        return None
    if key in {"multiquery", "hyde"}:
        return LangChainQueryExpander(key, ollama_host=ollama_host)
    raise ValueError(f"unknown expansion: {key}")


def _build_langchain_chain(kind: str, expansion_n: int, ollama_host: str | None):
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_ollama import ChatOllama

    prompt_text = (
        "Generate {n} short alternative search queries for a private photo search system. "
        "Keep them concrete, avoid explanations, one query per line.\nOriginal query: {query}"
        if kind == "multiquery"
        else "Write one concise hypothetical photo caption that would answer this search query. "
        "Avoid explanations.\nSearch query: {query}"
    )
    kwargs = {"model": _EXPANSION_MODEL}
    if ollama_host:
        kwargs["base_url"] = ollama_host
    return ChatPromptTemplate.from_template(prompt_text) | ChatOllama(**kwargs) | StrOutputParser()


def _coerce_text(value) -> str:
    return getattr(value, "content", value if isinstance(value, str) else str(value)).strip()


def _parse_lines(text: str) -> list[str]:
    return [
        _LINE_PREFIX_RE.sub("", line).strip(" \"'")
        for line in text.splitlines()
        if line.strip()
    ]


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result

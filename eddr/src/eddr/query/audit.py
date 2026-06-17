"""검색 품질 감사 — 캡션 오류와 검색 증폭을 분리해 기록한다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from eddr.db.repository import EddrDatabase, PhotoQueryFilters
from eddr.query.captions import parse_caption
from eddr.query.tools import (
    _LEXICAL_POOL,
    _OVERFETCH_FACTOR,
    _RRF_K,
    QUERY_EMBED_INSTRUCTION,
    _clamp,
)
from eddr.types import Embedding


class AuditEmbeddingClient(Protocol):
    """감사 실행에 필요한 질의 임베딩 클라이언트."""

    def embed_texts(self, texts: list[str]) -> list[Embedding]:
        """텍스트 목록을 임베딩 목록으로 변환한다."""
        ...


class AuditVectorStore(Protocol):
    """감사 실행에 필요한 벡터 검색 스토어."""

    def query(self, embedding: Embedding, k: int, where=None):
        """임베딩 기준 가까운 문서를 반환한다."""
        ...


@dataclass(frozen=True)
class CaptionAuditLabel:
    """사람이 붙이는 감사 라벨 — 시각 사실과 캡션 주장을 분리한다."""

    visual_target: bool | None
    caption_claims_target: bool | None
    review_label: str | None = None


@dataclass(frozen=True)
class KeywordAuditStat:
    """감사 질의 키워드 한 개의 캡션 문서 빈도."""

    keyword: str
    document_count: int


@dataclass(frozen=True)
class CaptionSearchAuditHit:
    """검색 결과 한 건의 provenance와 라벨 기반 오류 bucket."""

    photo_id: str
    rank: int
    fused_score: float
    vector_rank: int | None
    vector_distance: float | None
    vector_score: float
    lexical_rank: int | None
    lexical_score: float
    matched_keywords: tuple[str, ...]
    caption: str | None
    caption_keywords: tuple[str, ...]
    review_label: str | None
    bucket: str


@dataclass(frozen=True)
class CaptionSearchAuditReport:
    """단일 검색 질의에 대한 캡션 품질 감사 리포트."""

    query: str
    keywords: tuple[str, ...]
    keyword_stats: dict[str, KeywordAuditStat]
    hits: tuple[CaptionSearchAuditHit, ...]


def trace_caption_search(
    *,
    db: EddrDatabase,
    vector_store: AuditVectorStore,
    embedding_client: AuditEmbeddingClient,
    query: str,
    keywords: list[str] | None = None,
    k: int = 20,
    labels: dict[str, CaptionAuditLabel] | None = None,
    query_embed_template: str | None = QUERY_EMBED_INSTRUCTION,
) -> CaptionSearchAuditReport:
    """현재 검색 재료로 top-k provenance를 계산하되 DB와 Chroma를 변경하지 않는다."""
    k = _clamp(k)
    keywords_tuple = tuple(_clean_keyword(keyword) for keyword in keywords or () if keyword.strip())
    embed_text = query_embed_template.format(query=query) if query_embed_template else query
    embedding = embedding_client.embed_texts([embed_text])[0]

    keyword_stats = {
        keyword: KeywordAuditStat(keyword, db.count_caption_matches(_fts_phrase(keyword)))
        for keyword in keywords_tuple
    }
    lexical_ids = _lexical_ids(db, keywords_tuple)
    pool_k = k * _OVERFETCH_FACTOR
    while True:
        vector_hits = vector_store.query(embedding=embedding, k=pool_k)
        vector_ids: list[str] = []
        distance_by_id: dict[str, float | None] = {}
        for hit in vector_hits:
            if hit.photo_id and hit.photo_id not in distance_by_id:
                vector_ids.append(hit.photo_id)
                distance_by_id[hit.photo_id] = hit.distance

        fused_ids = _fuse_with_scores(vector_ids, lexical_ids)
        passed_all = db.filter_photo_ids(list(fused_ids), PhotoQueryFilters())
        passed_ids = passed_all[:k]
        if len(passed_ids) >= k or len(vector_hits) < pool_k:
            break
        pool_k *= _OVERFETCH_FACTOR

    vector_rank = {photo_id: rank for rank, photo_id in enumerate(vector_ids, start=1)}
    lexical_rank = {photo_id: rank for rank, photo_id in enumerate(lexical_ids, start=1)}
    label_map = labels or {}
    hits: list[CaptionSearchAuditHit] = []
    for rank, photo_id in enumerate(passed_ids, start=1):
        photo = db.get_photo(photo_id)
        if photo is None:
            continue
        caption_text = db.get_latest_caption(photo_id)
        parsed = parse_caption(caption_text) if caption_text else None
        matched_keywords = _matched_keywords(caption_text or "", keywords_tuple)
        v_rank = vector_rank.get(photo_id)
        l_rank = lexical_rank.get(photo_id)
        vector_score = _rrf_score(v_rank)
        lexical_score = _rrf_score(l_rank)
        hits.append(
            CaptionSearchAuditHit(
                photo_id=photo_id,
                rank=rank,
                fused_score=vector_score + lexical_score,
                vector_rank=v_rank,
                vector_distance=distance_by_id.get(photo_id),
                vector_score=vector_score,
                lexical_rank=l_rank,
                lexical_score=lexical_score,
                matched_keywords=matched_keywords,
                caption=parsed.body if parsed else None,
                caption_keywords=parsed.keywords if parsed else (),
                review_label=label_map.get(photo_id).review_label
                if label_map.get(photo_id) is not None
                else None,
                bucket=_bucket(label_map.get(photo_id)),
            )
        )

    return CaptionSearchAuditReport(
        query=query,
        keywords=keywords_tuple,
        keyword_stats=keyword_stats,
        hits=tuple(hits),
    )


def load_caption_audit_labels(path: Path) -> dict[str, CaptionAuditLabel]:
    """JSON 라벨 파일을 ``photo_id -> CaptionAuditLabel`` 맵으로 읽는다."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    labels: dict[str, CaptionAuditLabel] = {}
    for photo_id, value in raw.items():
        labels[str(photo_id)] = CaptionAuditLabel(
            visual_target=_optional_bool(value.get("visual_target")),
            caption_claims_target=_optional_bool(value.get("caption_claims_target")),
            review_label=value.get("review_label"),
        )
    return labels


def _lexical_ids(db: EddrDatabase, keywords: tuple[str, ...]) -> list[str]:
    if not keywords:
        return []
    match = " OR ".join(_fts_phrase(keyword) for keyword in keywords)
    return db.search_caption_photo_ids(match, limit=_LEXICAL_POOL)


def _fuse_with_scores(*ranked_lists: list[str]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, photo_id in enumerate(ranked, start=1):
            scores[photo_id] = scores.get(photo_id, 0.0) + _rrf_score(rank)
    return dict(sorted(scores.items(), key=lambda item: (-item[1], item[0])))


def _rrf_score(rank: int | None) -> float:
    return 0.0 if rank is None else 1.0 / (_RRF_K + rank)


def _matched_keywords(caption_text: str, keywords: tuple[str, ...]) -> tuple[str, ...]:
    lowered = caption_text.lower()
    return tuple(keyword for keyword in keywords if keyword.lower() in lowered)


def _bucket(label: CaptionAuditLabel | None) -> str:
    if label is None:
        return "unlabeled"
    visual = label.visual_target
    caption = label.caption_claims_target
    if visual is None or caption is None:
        return "unlabeled"
    if visual and caption:
        return "aligned_positive"
    if visual and not caption:
        return "caption_recall_gap"
    if not visual and caption:
        return "caption_false_positive"
    return "retrieval_noise"


def _fts_phrase(keyword: str) -> str:
    return f'"{_clean_keyword(keyword).replace(chr(34), " ")}"'


def _clean_keyword(keyword: str) -> str:
    return " ".join(keyword.strip().split())


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f"expected boolean or null label value, got {value!r}")

"""임베딩 기반 시맨틱 사진 검색 — 쿼리를 벡터로 변환해 가장 가까운 사진을 반환한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from eddr.db.repository import EddrDatabase
from eddr.types import Embedding, MetadataFilter


class QueryEmbeddingClient(Protocol):
    """텍스트 목록을 임베딩 벡터로 변환하는 클라이언트 프로토콜."""

    def embed_texts(self, texts: list[str]) -> list[Embedding]: ...


class VectorSearchStore(Protocol):
    """임베딩으로 가까운 문서를 조회하는 벡터 스토어 프로토콜."""

    def query(self, embedding: Embedding, k: int, where: MetadataFilter | None = None): ...


@dataclass(frozen=True)
class SemanticSearchResult:
    """시맨틱 검색 단일 결과 — 사진 메타데이터와 벡터 거리를 함께 담는다."""

    photo_id: str
    source: str
    source_uri: str
    image_path: str | None
    taken_at: str | None
    caption: str | None
    distance: float | None


def semantic_search(
    query: str,
    db: EddrDatabase,
    vector_store: VectorSearchStore,
    embedding_client: QueryEmbeddingClient,
    k: int,
    where: MetadataFilter | None = None,
) -> list[SemanticSearchResult]:
    """자연어 쿼리로 의미적으로 유사한 사진을 검색해 반환한다.

    Args:
        query: 검색할 자연어 질의문.
        db: 사진 메타데이터 및 캡션을 조회할 EDDR 데이터베이스.
        vector_store: 벡터 유사도 검색을 수행하는 스토어.
        embedding_client: 쿼리 문자열을 임베딩 벡터로 변환하는 클라이언트.
        k: 반환할 최대 결과 수.
        where: 결과를 좁히기 위한 메타데이터 필터 (선택).

    Returns:
        거리 기준으로 정렬된 SemanticSearchResult 목록.
    """
    embedding = embedding_client.embed_texts([query])[0]
    hits = vector_store.query(embedding=embedding, k=k, where=where)
    results: list[SemanticSearchResult] = []
    for hit in hits:
        photo = db.get_photo(hit.photo_id)
        if not photo:
            continue
        results.append(
            SemanticSearchResult(
                photo_id=hit.photo_id,
                source=photo.source,
                source_uri=photo.source_uri,
                image_path=photo.image_path,
                taken_at=photo.taken_at,
                caption=db.get_latest_caption(hit.photo_id) or hit.document,
                distance=hit.distance,
            )
        )
    return results

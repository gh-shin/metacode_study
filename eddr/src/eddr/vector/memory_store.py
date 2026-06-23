"""인메모리 벡터 스토어 — 테스트·프로토타입용 L2 거리 기반 유사도 검색."""

from __future__ import annotations

from dataclasses import dataclass

from eddr.types import Embedding, Metadata, MetadataFilter
from eddr.vector.chroma_store import VectorHit


@dataclass
class _MemoryVector:
    id: str
    embedding: Embedding
    document: str
    metadata: Metadata


class MemoryVectorStore:
    """dict 기반 인메모리 벡터 스토어.

    영구 저장 없이 ChromaVectorStore와 동일한 인터페이스를 제공한다.
    주로 단위 테스트에 사용된다.
    """

    def __init__(self):
        """빈 인메모리 스토어를 만든다."""
        self._items: dict[str, _MemoryVector] = {}

    def upsert(
        self,
        ids: list[str],
        embeddings: list[Embedding],
        documents: list[str],
        metadatas: list[Metadata],
    ) -> None:
        """벡터와 문서를 인메모리 스토어에 삽입하거나 갱신한다.

        Args:
            ids: 각 벡터의 고유 식별자 목록.
            embeddings: 부동소수점 벡터 목록.
            documents: 벡터화된 원본 텍스트 목록.
            metadatas: 각 벡터에 첨부할 메타데이터 딕셔너리 목록.

        Raises:
            ValueError: 네 인수의 길이가 서로 다를 때.
        """
        lengths = {len(ids), len(embeddings), len(documents), len(metadatas)}
        if len(lengths) != 1:
            raise ValueError("ids, embeddings, documents, and metadatas must have the same length")
        for vector_id, embedding, document, metadata in zip(
            ids, embeddings, documents, metadatas, strict=True
        ):
            self._items[vector_id] = _MemoryVector(vector_id, embedding, document, metadata)

    def query(
        self,
        embedding: Embedding,
        k: int,
        where: MetadataFilter | None = None,
    ) -> list[VectorHit]:
        """쿼리 임베딩과 L2 거리가 가장 가까운 k개의 벡터를 반환한다.

        Args:
            embedding: 검색 기준 쿼리 벡터.
            k: 반환할 최대 결과 수.
            where: 메타데이터 필터 조건. None이면 필터링 없이 전체 검색한다.

        Returns:
            L2 거리 오름차순으로 정렬된 VectorHit 리스트.
        """
        rows = list(self._items.values())
        if where:
            rows = [
                item
                for item in rows
                if all(item.metadata.get(key) == value for key, value in where.items())
            ]
        rows.sort(key=lambda item: _l2(embedding, item.embedding))
        return [
            VectorHit(
                id=item.id,
                photo_id=str(item.metadata.get("photo_id", "")),
                document=item.document,
                metadata=item.metadata,
                distance=_l2(embedding, item.embedding),
            )
            for item in rows[:k]
        ]

    def count(self) -> int:
        """스토어에 저장된 벡터 수를 반환한다.

        Returns:
            현재 저장된 벡터 수.
        """
        return len(self._items)


def _l2(left: Embedding, right: Embedding) -> float:
    return sum((a - b) ** 2 for a, b in zip(left, right, strict=True))

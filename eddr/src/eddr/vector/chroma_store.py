"""ChromaDB 기반 영구 벡터 스토어 — 캡션 임베딩 upsert·유사도 검색."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chromadb

from eddr.types import Embedding, Metadata, MetadataFilter


@dataclass(frozen=True)
class VectorHit:
    """벡터 검색 결과 한 건을 나타내는 불변 데이터 클래스.

    Attributes:
        id: 벡터 스토어 내 고유 식별자.
        photo_id: 연결된 사진의 식별자.
        document: 벡터화된 텍스트(캡션).
        metadata: 벡터와 함께 저장된 메타데이터 딕셔너리.
        distance: 쿼리 벡터와의 거리(낮을수록 유사). None이면 미계산.
    """

    id: str
    photo_id: str
    document: str
    metadata: Metadata
    distance: float | None


class ChromaVectorStore:
    """ChromaDB PersistentClient를 사용하는 영구 벡터 스토어.

    Attributes:
        path: ChromaDB 데이터가 저장되는 디렉터리 경로.
        client: chromadb.PersistentClient 인스턴스.
        collection: 사용 중인 ChromaDB 컬렉션.
    """

    def __init__(self, path: Path | str, collection_name: str = "eddr_caption_text_v1"):
        """Args:
        path: ChromaDB 데이터 디렉터리 경로. 없으면 자동 생성된다.
        collection_name: 사용할 컬렉션 이름. 없으면 새로 생성된다.
        """
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.path))
        self.collection = self.client.get_or_create_collection(collection_name)

    def upsert(
        self,
        ids: list[str],
        embeddings: list[Embedding],
        documents: list[str],
        metadatas: list[Metadata],
    ) -> None:
        """벡터와 문서를 컬렉션에 삽입하거나 갱신한다.

        ids가 비어 있으면 아무 작업도 하지 않는다.

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
        if not ids:
            return
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def query(
        self,
        embedding: Embedding,
        k: int,
        where: MetadataFilter | None = None,
    ) -> list[VectorHit]:
        """쿼리 임베딩과 가장 가까운 k개의 벡터를 반환한다.

        Args:
            embedding: 검색 기준 쿼리 벡터.
            k: 반환할 최대 결과 수.
            where: 메타데이터 필터 조건. None이면 필터링 없이 검색한다.

        Returns:
            거리 오름차순으로 정렬된 VectorHit 리스트.
        """
        result = self.collection.query(
            query_embeddings=[embedding],
            n_results=k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        hits: list[VectorHit] = []
        for idx, vector_id in enumerate(ids):
            metadata = metadatas[idx] or {}
            hits.append(
                VectorHit(
                    id=vector_id,
                    photo_id=str(metadata.get("photo_id", "")),
                    document=documents[idx],
                    metadata=dict(metadata),
                    distance=distances[idx] if distances else None,
                )
            )
        return hits

    def count(self) -> int:
        """컬렉션에 저장된 벡터 수를 반환한다.

        Returns:
            컬렉션의 전체 벡터 수.
        """
        return int(self.collection.count())

"""LangChain BM25Retriever 기반 한국어 notes lexical leg."""

from __future__ import annotations

from eddr.db.repository import EddrDatabase


class NotesBM25Index:
    """SQLite notes 텍스트로 만든 count-gated BM25 인덱스."""

    def __init__(self, notes: list[tuple[str, str]], retriever=None):
        """notes 개수와 LangChain BM25 retriever를 보관한다."""
        self._count = len(notes)
        self.retriever = retriever

    @classmethod
    def from_db(cls, db: EddrDatabase) -> NotesBM25Index:
        """DB notes로 BM25Retriever를 만든다. notes 0건이면 의존성 import도 생략한다."""
        notes = db.list_notes()
        if not notes:
            return cls([])

        from langchain_community.retrievers import BM25Retriever
        from langchain_core.documents import Document

        tokenizer = _kiwi_tokenizer()
        documents = [
            Document(page_content=text, metadata={"photo_id": photo_id})
            for photo_id, text in notes
        ]
        return cls(
            notes,
            retriever=BM25Retriever.from_documents(
                documents,
                preprocess_func=tokenizer,
            ),
        )

    def count(self) -> int:
        """색인된 notes 수."""
        return self._count

    def search(self, query: str, k: int) -> list[str]:
        """질의와 가까운 note의 photo_id를 BM25 순위로 반환한다."""
        if self.retriever is None or self._count == 0:
            return []
        self.retriever.k = k
        docs = self.retriever.invoke(query)
        return [doc.metadata["photo_id"] for doc in docs if "photo_id" in doc.metadata]


def _kiwi_tokenizer():
    from kiwipiepy import Kiwi

    kiwi = Kiwi()

    def tokenize(text: str) -> list[str]:
        return [token.form for token in kiwi.tokenize(text)]

    return tokenize

"""Ollama 비전 캡션·임베딩 배치 처리 — 단일호스트 및 듀얼호스트(동시) 실행을 지원한다."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from eddr.db.repository import EddrDatabase, PhotoRecord
from eddr.types import Embedding, Metadata


class CaptionTextVectorStore(Protocol):
    """캡션 텍스트 임베딩을 저장하는 벡터 스토어 프로토콜."""

    def upsert(
        self,
        ids: list[str],
        embeddings: list[Embedding],
        documents: list[str],
        metadatas: list[Metadata],
    ) -> None: ...


class VisionClient(Protocol):
    """캡션 생성·임베딩 기능을 제공하는 비전 클라이언트 프로토콜."""

    caption_model: str
    embedding_model: str

    def caption_photo(self, photo: PhotoRecord) -> str: ...

    def embed_texts(self, texts: list[str]) -> list[Embedding]: ...


@dataclass(frozen=True)
class VisionBatchReport:
    """배치 실행 결과 요약 — 성공·실패 사진 수를 담는다."""

    processed: int
    failed: int


@dataclass(frozen=True)
class _CaptionResult:
    """dual 배치 워커가 결과 큐로 넘기는 태그드 결과.

    ``status`` 값에 따라 의미 있는 필드가 달라진다.

    - ``"ok"``: ``caption``, ``caption_model`` 사용
    - ``"missing"``: 추가 필드 없음(이미지 파일 부재)
    - ``"error"``: ``error`` 사용(캡션 생성 중 예외)
    """

    status: str  # "ok" | "missing" | "error"
    photo: PhotoRecord
    caption: str | None = None
    caption_model: str | None = None
    error: Exception | None = None


def run_caption_text_batch(
    db: EddrDatabase,
    vector_store: CaptionTextVectorStore,
    vision_client: VisionClient,
    limit: int,
) -> VisionBatchReport:
    """미처리 사진에 대해 캡션 생성·임베딩·DB 저장을 단일 스레드로 순차 실행한다.

    Args:
        db: EDDR SQLite 데이터베이스 접근 객체.
        vector_store: 캡션 임베딩을 upsert할 벡터 스토어.
        vision_client: 캡션 생성·임베딩을 수행할 비전 클라이언트.
        limit: 이번 배치에서 처리할 최대 사진 수.

    Returns:
        처리 성공·실패 건수를 담은 ``VisionBatchReport``.
    """
    processed = failed = 0
    for photo in db.pending_vision_photos(limit=limit):
        image_path = Path(photo.image_path or "")
        if not image_path.exists():
            db.record_error(photo.id, "vision", f"image_path does not exist: {image_path}")
            db.update_status(photo.id, "missing_image")
            failed += 1
            continue
        try:
            caption = vision_client.caption_photo(photo)
            _persist_caption(
                db,
                vector_store,
                photo=photo,
                caption=caption,
                caption_model=vision_client.caption_model,
                embed_client=vision_client,
            )
            processed += 1
        except Exception as exc:
            db.record_error(photo.id, "vision", str(exc))
            failed += 1
    return VisionBatchReport(processed=processed, failed=failed)


def _persist_caption(
    db: EddrDatabase,
    vector_store: CaptionTextVectorStore,
    *,
    photo: PhotoRecord,
    caption: str,
    caption_model: str,
    embed_client: VisionClient,
) -> None:
    """캡션을 임베딩해 벡터 스토어와 DB에 저장하고 사진 상태를 caption_done으로 갱신한다."""
    embedding = embed_client.embed_texts([caption])[0]
    vector_id = f"caption_text:{photo.id}:{embed_client.embedding_model}"
    db.upsert_caption(photo.id, caption_model, "en", caption)
    vector_store.upsert(
        ids=[vector_id],
        embeddings=[embedding],
        documents=[caption],
        metadatas=[
            {
                "photo_id": photo.id,
                "source": photo.source,
                "kind": "caption_text",
                "model_id": embed_client.embedding_model,
            }
        ],
    )
    db.upsert_embedding_record(
        photo_id=photo.id,
        kind="caption_text",
        model_id=embed_client.embedding_model,
        vector_id=vector_id,
        dimensions=len(embedding),
    )
    db.update_status(photo.id, "caption_done")


def run_caption_text_batch_dual(
    db: EddrDatabase,
    vector_store: CaptionTextVectorStore,
    local_client: VisionClient,
    remote_client: VisionClient,
    limit: int,
    embed_client: VisionClient | None = None,
) -> VisionBatchReport:
    """Caption photos across two Ollama servers concurrently; embed + persist locally.

    Caption (the GPU-bound bottleneck) is distributed across ``local_client`` and
    ``remote_client`` via two worker threads pulling from a shared queue. Embedding,
    Chroma upsert and DB writes all run single-threaded through ``embed_client``
    (defaults to ``local_client``) so the vector space stays consistent and
    SQLite/Chroma are never written concurrently. Status is updated per photo, so a
    crashed run resumes by re-selecting still-pending photos.
    """
    embed_client = embed_client or local_client
    photos = db.pending_vision_photos(limit=limit)
    work: queue.Queue[PhotoRecord] = queue.Queue()
    for photo in photos:
        work.put(photo)
    results: queue.Queue[_CaptionResult] = queue.Queue()

    def worker(client: VisionClient) -> None:
        while True:
            try:
                photo = work.get_nowait()
            except queue.Empty:
                return
            image_path = Path(photo.image_path or "")
            if not image_path.exists():
                results.put(_CaptionResult(status="missing", photo=photo))
                continue
            try:
                caption = client.caption_photo(photo)
                results.put(
                    _CaptionResult(
                        status="ok",
                        photo=photo,
                        caption=caption,
                        caption_model=client.caption_model,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - reported per photo
                results.put(_CaptionResult(status="error", photo=photo, error=exc))

    threads = [
        threading.Thread(target=worker, args=(client,), daemon=True)
        for client in (local_client, remote_client)
    ]
    for thread in threads:
        thread.start()

    processed = failed = 0
    for _ in range(len(photos)):
        result = results.get()
        if result.status == "ok":
            try:
                _persist_caption(
                    db,
                    vector_store,
                    photo=result.photo,
                    caption=result.caption,
                    caption_model=result.caption_model,
                    embed_client=embed_client,
                )
                processed += 1
            except Exception as exc:  # noqa: BLE001 - reported per photo
                db.record_error(result.photo.id, "vision", str(exc))
                failed += 1
        elif result.status == "missing":
            db.record_error(
                result.photo.id,
                "vision",
                f"image_path does not exist: {result.photo.image_path}",
            )
            db.update_status(result.photo.id, "missing_image")
            failed += 1
        else:  # "error"
            db.record_error(result.photo.id, "vision", str(result.error))
            failed += 1

    for thread in threads:
        thread.join()
    return VisionBatchReport(processed=processed, failed=failed)

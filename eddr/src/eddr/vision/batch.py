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
    ) -> None:
        """벡터·문서·메타데이터를 같은 순서로 일괄 저장(갱신)한다."""
        ...


class VisionClient(Protocol):
    """캡션 생성·임베딩 기능을 제공하는 비전 클라이언트 프로토콜."""

    caption_model: str
    embedding_model: str

    def caption_photo(self, photo: PhotoRecord) -> str:
        """사진 한 장의 영어 캡션을 생성한다."""
        ...

    def embed_texts(self, texts: list[str]) -> list[Embedding]:
        """텍스트 목록을 같은 순서의 임베딩 목록으로 변환한다."""
        ...


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
    persist_vector: bool = True,
) -> None:
    """캡션을 DB에 저장하고, persist_vector=True이면 임베딩·벡터 스토어도 갱신한다.

    Args:
        db: EDDR SQLite 데이터베이스 접근 객체.
        vector_store: 캡션 임베딩을 upsert할 벡터 스토어.
        photo: 대상 사진 레코드.
        caption: 저장할 캡션 텍스트.
        caption_model: 캡션을 생성한 모델 ID.
        embed_client: 임베딩을 수행할 클라이언트.
        persist_vector: False이면 embed_texts·vector_store.upsert·upsert_embedding_record를
            모두 건너뛰고 캡션 텍스트와 상태만 DB에 기록한다. Chroma 멀티스레드 데드락 회피용.
    """
    db.upsert_caption(photo.id, caption_model, "en", caption)
    if persist_vector:
        embedding = embed_client.embed_texts([caption])[0]
        vector_id = f"caption_text:{photo.id}:{embed_client.embedding_model}"
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
    """캡션을 두 Ollama 서버에 분산 생성하고, 임베딩·저장은 로컬 단일로 수행한다.

    GPU 병목인 캡션 생성은 공유 큐에서 꺼내 가는 워커 스레드 2개로
    ``local_client``·``remote_client``에 분산한다. 임베딩·Chroma upsert·DB 쓰기는
    전부 ``embed_client``(기본 ``local_client``) 단일 스레드로 흘러 벡터 공간이
    일관되고 SQLite/Chroma 동시 쓰기가 없다. 사진마다 status를 갱신하므로
    중단된 실행은 pending 사진 재선택으로 이어서 돌릴 수 있다 (ADR-0007).
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
            except Exception as exc:
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
            except Exception as exc:
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


def _caption_one(client: VisionClient, photo: PhotoRecord) -> _CaptionResult:
    """사진 한 장을 ``client``로 캡션해 태그드 결과로 만든다(파일 부재·예외 포함)."""
    image_path = Path(photo.image_path or "")
    if not image_path.exists():
        return _CaptionResult(status="missing", photo=photo)
    try:
        caption = client.caption_photo(photo)
        return _CaptionResult(
            status="ok",
            photo=photo,
            caption=caption,
            caption_model=client.caption_model,
        )
    except Exception as exc:
        return _CaptionResult(status="error", photo=photo, error=exc)


def run_caption_text_batch_routed_dual(
    db: EddrDatabase,
    vector_store: CaptionTextVectorStore,
    embed_client: VisionClient,
    *,
    doc_client: VisionClient,
    nondoc_local_client: VisionClient,
    nondoc_remote_client: VisionClient,
    doc_photos: list[PhotoRecord],
    nondoc_photos: list[PhotoRecord],
    persist_vector: bool = True,
) -> VisionBatchReport:
    """도메인 라우팅 투트랙 재캡션 — 문서는 로컬 OCR 모델, 비문서는 gemma 분산.

    문서·텍스트성 사진(``doc_photos``)은 OCR 우위인 ``doc_client``(로컬 qwen3-vl:8b)로,
    비문서 사진(``nondoc_photos``)은 ``nondoc_remote_client``(원격 gemma4:31b @ macmini)로
    캡션한다. 핵심은 **로컬 유휴 방지**다: 로컬 워커는 먼저 문서 큐를 ``doc_client``로
    비우고, 비면 ``nondoc_local_client``(로컬 gemma4:31b)로 전환해 남은 비문서를 원격과
    함께 처리한다.

    GPU 병목인 캡션 생성만 워커 스레드 2개(원격·로컬)에 분산하고, 임베딩·Chroma
    upsert·DB 쓰기는 ``embed_client`` 단일 스레드로 흘러 벡터 공간이 일관되고
    SQLite/Chroma 동시 쓰기가 없다. 사진마다 status를 갱신하므로 중단된 실행은 이어서
    돌릴 수 있다(ADR-0007). 결과의 ``caption_model``은 실제 캡션한 client의 것을
    보존해, 어느 모델이 캡션했는지 DB ``model_id``에 그대로 기록된다.

    Args:
        db: EDDR SQLite 데이터베이스 접근 객체.
        vector_store: 캡션 임베딩을 upsert할 벡터 스토어.
        embed_client: 임베딩·persist를 단독 수행할 클라이언트(벡터 공간 일관성).
        doc_client: 문서 사진 캡션 클라이언트(로컬 qwen3-vl:8b).
        nondoc_local_client: 로컬이 문서 소진 후 전환할 비문서 캡션 클라이언트(로컬 gemma4:31b).
        nondoc_remote_client: 비문서 캡션 클라이언트(원격 gemma4:31b @ macmini).
        doc_photos: 문서·텍스트성 사진 레코드 목록.
        nondoc_photos: 비문서 사진 레코드 목록.
        persist_vector: False이면 Chroma upsert·임베딩을 건너뛰고 캡션 텍스트만 DB에 저장한다.
            ``--no-vector`` CLI 플래그로 활성화 — 워커 스레드 도중 Chroma 데드락 회피용.

    Returns:
        처리 성공·실패 건수를 담은 ``VisionBatchReport``.
    """
    doc_queue: queue.Queue[PhotoRecord] = queue.Queue()
    for photo in doc_photos:
        doc_queue.put(photo)
    nondoc_queue: queue.Queue[PhotoRecord] = queue.Queue()
    for photo in nondoc_photos:
        nondoc_queue.put(photo)
    results: queue.Queue[_CaptionResult] = queue.Queue()

    def remote_worker() -> None:
        # 원격은 비문서 큐만 처리한다(비면 즉시 종료).
        while True:
            try:
                photo = nondoc_queue.get_nowait()
            except queue.Empty:
                return
            results.put(_caption_one(nondoc_remote_client, photo))

    def local_worker() -> None:
        # 먼저 문서 큐를 비우고, 비면 비문서 큐로 전환해 원격과 함께 처리한다.
        while True:
            try:
                photo = doc_queue.get_nowait()
            except queue.Empty:
                break
            results.put(_caption_one(doc_client, photo))
        while True:
            try:
                photo = nondoc_queue.get_nowait()
            except queue.Empty:
                return
            results.put(_caption_one(nondoc_local_client, photo))

    threads = [
        threading.Thread(target=remote_worker, daemon=True),
        threading.Thread(target=local_worker, daemon=True),
    ]
    for thread in threads:
        thread.start()

    processed = failed = 0
    for _ in range(len(doc_photos) + len(nondoc_photos)):
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
                    persist_vector=persist_vector,
                )
                processed += 1
            except Exception as exc:
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

"""서버 전역 상태·경로 계약 — 수명주기 단일점 (ADR-0008, prd §6-e 규율 ①).

전역 상태(서비스·추출기)는 이 모듈의 AppState 한 곳에만 둔다 — 멀티유저
전환 시 이 클래스만 세션 스코프로 바꾸면 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Request

from eddr.geocode.nominatim import NominatimClient
from eddr.query.extract import QueryExtractor
from eddr.query.tools import QueryService

if TYPE_CHECKING:
    from eddr.vector.chroma_store import ChromaVectorStore

# 메모 임베딩 컬렉션 — 캡션 컬렉션(eddr_caption_text_v1) 재구축과 격리 (prd §6-d).
NOTE_COLLECTION = "eddr_note_text_v1"


@dataclass(frozen=True)
class ServerConfig:
    """서버 기동 설정 — 데이터 경로는 전부 EDDR_ROOT에서 파생 가능 (ADR-0008).

    Attributes:
        root: EDDR_ROOT — 상대 image_path·기본 데이터 경로의 기준 디렉터리.
        db_path: SQLite 파일 경로.
        chroma_path: Chroma 데이터 디렉터리.
        ollama_host: 질의 추출기(QueryExtractor)의 Ollama 서버 URL.
            None이면 기본 로컬 호스트.
    """

    root: Path
    db_path: Path
    chroma_path: Path
    ollama_host: str | None = None


class AppState:
    """프로세스 전역 1개 — 질의 서비스·질의 추출기를 보유한다.

    검색 라우트는 읽기 전용·무상태라 직렬화 락이 없다 (prd §6-c) —
    ollama 동시성은 ollama 큐에 위임한다.

    Attributes:
        config: 기동 설정.
        service: 검색 서비스 — 라우트의 직접 조회(상세·경로)에도 쓴다.
        extractor: 질의 추출기 (D26 M3, /api/search) — 검색 미사용 테스트는 None 허용.
        geocoder: Nominatim 클라이언트 (D26 M4) — 프로세스 1개로 1 req/s를
            일원화한다(ADR-0009 §3). 테스트는 fake를 주입한다.
        note_store: 메모 임베딩 컬렉션(NOTE_COLLECTION) 핸들 (D26 M5) — note
            라우트(upsert·삭제)와 QueryService note leg가 같은 핸들을 공유한다.
            None이면 메모 저장은 되고 임베딩만 생략된다(embedded:false).
        thumb_dir: 썸네일 캐시 디렉터리.
    """

    def __init__(
        self,
        config: ServerConfig,
        service: QueryService,
        extractor: QueryExtractor | None = None,
        geocoder: NominatimClient | None = None,
        note_store: ChromaVectorStore | None = None,
    ):
        """전역 상태를 조립한다 — 각 인자의 역할은 클래스 Attributes 참조."""
        self.config = config
        self.service = service
        self.extractor = extractor
        self.geocoder = geocoder or NominatimClient()
        self.note_store = note_store
        self.thumb_dir = config.root / "data" / "cache" / "thumbs"


def resolve_image_path(root: Path, image_path: str) -> Path:
    """DB image_path를 실제 파일 경로로 푼다 — 상대경로는 EDDR_ROOT 기준 (ADR-0008).

    라우트는 photo_id 외의 경로 입력을 받지 않으므로 인자는 항상 DB에서 온
    경로다 — path traversal 차단 계약의 일부.
    """
    path = Path(image_path)
    return path if path.is_absolute() else root / path


def build_state(config: ServerConfig) -> AppState:
    """실데이터로 AppState를 조립한다 — serve_api 기동 경로."""
    from eddr.db.repository import EddrDatabase
    from eddr.vector.chroma_store import ChromaVectorStore
    from eddr.vision.ollama_client import OllamaVisionClient

    db = EddrDatabase(config.db_path)
    db.initialize()
    # 메모 컬렉션 핸들 — note 라우트와 QueryService note leg가 공유 (D26 M5).
    note_store = ChromaVectorStore(config.chroma_path, collection_name=NOTE_COLLECTION)
    service = QueryService(
        db,
        vector_store=ChromaVectorStore(config.chroma_path),
        embedding_client=OllamaVisionClient(),
        note_store=note_store,
    )
    # 질의 추출기 — --ollama-host가 추출기 host로 연결된다 (D26 M3, prd §6-c).
    extractor = QueryExtractor(host=config.ollama_host)
    return AppState(config, service, extractor=extractor, note_store=note_store)


def get_state(request: Request) -> AppState:
    """FastAPI 의존성 — create_app이 app.state.eddr에 둔 전역 AppState를 꺼낸다."""
    return request.app.state.eddr

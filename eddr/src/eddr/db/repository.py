"""SQLite 기반 사진 메타데이터 저장소 — photos/captions/embeddings 테이블 스키마와 CRUD."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

# 코드 측 계약(SSoT) — 설계 문서(PLAN/CONTEXT/wiki)와 일치해야 한다.
# drift 시 doc-contract hook이 차단한다.
VALID_SOURCES = ("photos_library", "google_takeout", "local")
INDEXING_STATUSES = (
    "meta_done",
    "missing_image",
    "caption_done",
    "skipped_video",
    "trip_assigned",
)


@dataclass(frozen=True)
class PhotoRecord:
    """사진 한 장의 메타데이터를 나타내는 불변 도메인 모델.

    Attributes:
        id: 소스와 콘텐츠 해시로 구성된 전역 고유 식별자 (예: ``google_takeout:<hash>``).
        source: 데이터 출처 식별자 (예: ``photos_library``, ``google_takeout``).
        source_uri: 소스 내부 식별자 (파일 경로 또는 UUID).
        image_path: 로컬 파일시스템의 실제 이미지 경로.
        content_hash: BLAKE3 또는 SHA-256 기반 파일 내용 해시.
        perceptual_hash: 시각적 유사도 비교용 dhash.
        taken_at: ISO 8601 형식의 촬영 일시.
        latitude: GPS 위도.
        longitude: GPS 경도.
        width: 이미지 가로 픽셀 수.
        height: 이미지 세로 픽셀 수.
        camera_make: 카메라 제조사.
        camera_model: 카메라 모델명.
        indexing_status: 인덱싱 진행 단계 (예: ``meta_done``, ``caption_done``).
    """

    id: str
    source: str
    source_uri: str
    image_path: str | None = None
    content_hash: str | None = None
    perceptual_hash: str | None = None
    taken_at: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    width: int | None = None
    height: int | None = None
    camera_make: str | None = None
    camera_model: str | None = None
    indexing_status: str = "meta_done"


class EddrDatabase:
    """SQLite 파일 기반 EDDR 저장소 접근 계층.

    photos, captions, embeddings, index_errors 테이블을 관리하며
    각 연산마다 새 Connection을 열고 닫는다.

    Attributes:
        path: SQLite 데이터베이스 파일 경로.
    """

    def __init__(self, path: Path | str):
        """Args:
        path: SQLite 파일 경로. 부모 디렉터리가 없으면 자동 생성된다.
        """
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        """데이터베이스에 연결하고 sqlite3.Connection을 반환한다.

        부모 디렉터리가 없으면 자동 생성하고, row_factory와 foreign_keys를 설정한다.

        Returns:
            설정이 완료된 sqlite3.Connection 객체.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        """photos, captions, embeddings, index_errors 테이블과 인덱스를 생성한다.

        이미 존재하는 경우 아무 작업도 하지 않는다 (CREATE IF NOT EXISTS).
        """
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS photos (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_uri TEXT NOT NULL,
                    image_path TEXT,
                    content_hash TEXT,
                    perceptual_hash TEXT,
                    taken_at TEXT,
                    latitude REAL,
                    longitude REAL,
                    width INTEGER,
                    height INTEGER,
                    camera_make TEXT,
                    camera_model TEXT,
                    indexing_status TEXT NOT NULL DEFAULT 'meta_done',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source, source_uri)
                );

                CREATE INDEX IF NOT EXISTS idx_photos_status
                    ON photos(indexing_status);
                CREATE INDEX IF NOT EXISTS idx_photos_content_hash
                    ON photos(content_hash);

                CREATE TABLE IF NOT EXISTS captions (
                    photo_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    lang TEXT NOT NULL,
                    text TEXT NOT NULL,
                    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(photo_id, model_id, lang),
                    FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS embeddings (
                    photo_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    vector_id TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(photo_id, kind, model_id),
                    FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS index_errors (
                    photo_id TEXT,
                    stage TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(photo_id) REFERENCES photos(id) ON DELETE CASCADE
                );
                """
            )

    def upsert_photo(self, photo: PhotoRecord) -> None:
        """PhotoRecord를 photos 테이블에 삽입하거나 갱신한다.

        id 충돌 시 source_uri·content_hash 등 메타 필드를 덮어쓰고
        updated_at을 현재 시각으로 갱신한다. 단 indexing_status는
        기존 행이 vision 이후 단계(caption_done·trip_assigned·skipped_video)면
        보존한다 — 재적재(meta_done)가 파이프라인 진행 상태를 리셋하지 않도록.

        Args:
            photo: 삽입 또는 갱신할 PhotoRecord 객체.
        """
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO photos (
                    id, source, source_uri, image_path, content_hash,
                    perceptual_hash, taken_at, latitude, longitude, width, height,
                    camera_make, camera_model, indexing_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    source = excluded.source,
                    source_uri = excluded.source_uri,
                    image_path = excluded.image_path,
                    content_hash = excluded.content_hash,
                    perceptual_hash = excluded.perceptual_hash,
                    taken_at = excluded.taken_at,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    width = excluded.width,
                    height = excluded.height,
                    camera_make = excluded.camera_make,
                    camera_model = excluded.camera_model,
                    indexing_status = CASE
                        WHEN photos.indexing_status IN (
                            'caption_done', 'trip_assigned', 'skipped_video'
                        )
                        THEN photos.indexing_status
                        ELSE excluded.indexing_status
                    END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    photo.id,
                    photo.source,
                    photo.source_uri,
                    photo.image_path,
                    photo.content_hash,
                    photo.perceptual_hash,
                    photo.taken_at,
                    photo.latitude,
                    photo.longitude,
                    photo.width,
                    photo.height,
                    photo.camera_make,
                    photo.camera_model,
                    photo.indexing_status,
                ),
            )

    def upsert_caption(self, photo_id: str, model_id: str, lang: str, text: str) -> None:
        """사진 캡션을 captions 테이블에 삽입하거나 갱신한다.

        (photo_id, model_id, lang) 복합 키 충돌 시 text와 generated_at을 갱신한다.

        Args:
            photo_id: 대상 사진의 식별자.
            model_id: 캡션을 생성한 모델 식별자 (예: ``llava:7b``).
            lang: 캡션 언어 코드 (예: ``ko``, ``en``).
            text: 캡션 본문.
        """
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO captions(photo_id, model_id, lang, text)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(photo_id, model_id, lang) DO UPDATE SET
                    text = excluded.text,
                    generated_at = CURRENT_TIMESTAMP
                """,
                (photo_id, model_id, lang, text),
            )

    def upsert_embedding_record(
        self,
        photo_id: str,
        kind: str,
        model_id: str,
        vector_id: str,
        dimensions: int,
    ) -> None:
        """임베딩 레코드를 embeddings 테이블에 삽입하거나 갱신한다.

        (photo_id, kind, model_id) 복합 키 충돌 시 vector_id·dimensions·created_at을 갱신한다.

        Args:
            photo_id: 대상 사진의 식별자.
            kind: 임베딩 종류 (예: ``caption_text``; image leg는 후속).
            model_id: 임베딩을 생성한 모델 식별자.
            vector_id: 벡터 스토어 내 식별자.
            dimensions: 벡터 차원 수.
        """
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO embeddings(photo_id, kind, model_id, vector_id, dimensions)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(photo_id, kind, model_id) DO UPDATE SET
                    vector_id = excluded.vector_id,
                    dimensions = excluded.dimensions,
                    created_at = CURRENT_TIMESTAMP
                """,
                (photo_id, kind, model_id, vector_id, dimensions),
            )

    def update_status(self, photo_id: str, status: str) -> None:
        """사진의 indexing_status와 updated_at을 갱신한다.

        Args:
            photo_id: 상태를 변경할 사진의 식별자.
            status: 새로운 인덱싱 상태 (예: ``caption_done``, ``skipped_video``).
        """
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE photos
                SET indexing_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, photo_id),
            )

    def record_error(self, photo_id: str | None, stage: str, message: str) -> None:
        """인덱싱 오류를 index_errors 테이블에 기록한다.

        Args:
            photo_id: 오류가 발생한 사진의 식별자. 사진과 무관한 오류면 None.
            stage: 오류가 발생한 처리 단계 (예: ``load_takeout``, ``caption``).
            message: 오류 메시지.
        """
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO index_errors(photo_id, stage, message) VALUES (?, ?, ?)",
                (photo_id, stage, message),
            )

    def pending_vision_photos(self, limit: int) -> list[PhotoRecord]:
        """비전 처리가 아직 완료되지 않은 사진을 촬영 일시 순으로 반환한다.

        image_path가 있고 indexing_status가 caption_done·trip_assigned·skipped_video가
        아닌 사진을 대상으로 한다.

        Args:
            limit: 반환할 최대 레코드 수.

        Returns:
            PhotoRecord 리스트. 촬영 일시 없는 항목은 뒤로 정렬된다.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*
                FROM photos p
                WHERE p.image_path IS NOT NULL
                  AND p.indexing_status NOT IN ('caption_done', 'trip_assigned', 'skipped_video')
                ORDER BY p.taken_at IS NULL, p.taken_at, p.id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_photo(r) for r in rows]

    def pending_vision_photos_stratified(self, limit: int) -> list[PhotoRecord]:
        """소스별로 균등하게 샘플링한 비전 미처리 사진을 반환한다.

        소스(photos_library, google_takeout 등)마다 ROW_NUMBER를 매겨
        소스 간 편향 없이 limit 건을 선택한다.

        Args:
            limit: 반환할 최대 레코드 수.

        Returns:
            소스별로 교차 정렬된 PhotoRecord 리스트.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT p.*,
                           ROW_NUMBER() OVER (
                               PARTITION BY p.source
                               ORDER BY p.taken_at IS NULL, p.taken_at, p.id
                           ) AS _rn
                    FROM photos p
                    WHERE p.image_path IS NOT NULL
                      AND p.indexing_status NOT IN (
                          'caption_done', 'trip_assigned', 'skipped_video'
                      )
                )
                ORDER BY _rn, source
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_photo(r) for r in rows]

    def get_photo(self, photo_id: str) -> PhotoRecord | None:
        """photo_id로 단일 사진 레코드를 조회한다.

        Args:
            photo_id: 조회할 사진의 식별자.

        Returns:
            해당 사진의 PhotoRecord, 없으면 None.
        """
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM photos WHERE id = ?", (photo_id,)).fetchone()
        return _row_to_photo(row) if row else None

    def get_latest_caption(self, photo_id: str) -> str | None:
        """사진의 가장 최근 캡션 텍스트를 반환한다.

        Args:
            photo_id: 조회할 사진의 식별자.

        Returns:
            가장 최근에 생성된 캡션 문자열, 없으면 None.
        """
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT text
                FROM captions
                WHERE photo_id = ?
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (photo_id,),
            ).fetchone()
        return str(row["text"]) if row else None

    def count_photos(self) -> int:
        """photos 테이블의 전체 레코드 수를 반환한다.

        Returns:
            photos 테이블의 행 수.
        """
        return self._count("photos")

    def count_captions(self) -> int:
        """captions 테이블의 전체 레코드 수를 반환한다.

        Returns:
            captions 테이블의 행 수.
        """
        return self._count("captions")

    def count_embeddings(self, kind: str | None = None) -> int:
        """embeddings 테이블의 레코드 수를 반환한다.

        Args:
            kind: 특정 종류만 집계할 경우 지정 (예: ``caption_text``). None이면 전체 집계.

        Returns:
            조건에 맞는 embeddings 테이블의 행 수.
        """
        if kind is None:
            return self._count("embeddings")
        with self.connect() as conn:
            return int(
                conn.execute("SELECT COUNT(*) FROM embeddings WHERE kind = ?", (kind,)).fetchone()[
                    0
                ]
            )

    def _count(self, table: str) -> int:
        with self.connect() as conn:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _row_to_photo(row: sqlite3.Row) -> PhotoRecord:
    return PhotoRecord(
        id=row["id"],
        source=row["source"],
        source_uri=row["source_uri"],
        image_path=row["image_path"],
        content_hash=row["content_hash"],
        perceptual_hash=row["perceptual_hash"],
        taken_at=row["taken_at"],
        latitude=row["latitude"],
        longitude=row["longitude"],
        width=row["width"],
        height=row["height"],
        camera_make=row["camera_make"],
        camera_model=row["camera_model"],
        indexing_status=row["indexing_status"],
    )

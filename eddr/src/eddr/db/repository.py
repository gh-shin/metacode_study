"""SQLite 기반 사진 메타데이터 저장소 — photos/captions/embeddings 테이블 스키마와 CRUD."""

from __future__ import annotations

import math
import sqlite3
from collections import Counter
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
        country: reverse geocode 국가명 (enrichment — upsert_photo는 쓰지 않음).
        city: reverse geocode 시/도명 (enrichment).
        district: reverse geocode 구/동명 (enrichment).
        trip_id: 배정된 trip 식별자 (enrichment).
        duplicate_of: cross-source dedup canonical 사진 id (enrichment, PLAN §4.2).

    enrichment 필드는 dedup·geocode·trip 단계가 전용 UPDATE 메서드로 채운다.
    ``upsert_photo``(소스 재적재 경로)는 이 필드들을 건드리지 않아 재적재가
    enrichment 결과를 리셋하지 않는다.
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
    country: str | None = None
    city: str | None = None
    district: str | None = None
    trip_id: str | None = None
    duplicate_of: str | None = None


@dataclass(frozen=True)
class TripRecord:
    """trips 테이블 한 행을 나타내는 불변 도메인 모델.

    Attributes:
        id: 결정적 trip 식별자 (예: ``trip_20190601_01``).
        name: 자동 생성 이름 (예: ``이탈리아 여행 2018-04``).
        start_at: 시작 시각 — naive UTC ``YYYY-MM-DD HH:MM:SS``.
        end_at: 끝 시각 — 동일 포맷.
        photo_count: 질의 레이어 노출 기준 사진 수 (duplicate 제외).
        center_lat: 구간 사진 평균 위도 — 로컬 계산용, LLM 응답 미노출 (ADR-0001).
        center_lng: 구간 사진 평균 경도 — 동일.
    """

    id: str
    name: str
    start_at: str
    end_at: str
    photo_count: int
    center_lat: float | None
    center_lng: float | None


@dataclass(frozen=True)
class PhotoQueryFilters:
    """질의 레이어 사진 필터 — 검색 서비스(QueryService)의 데이터 경로와 1:1 대응.

    장소 조건(countries·cities·trip_ids)은 단일 OR 그룹으로 결합된다
    (ADR-0009, prd §6-c) — geocode 없는 사진도 trip 소속이면 장소 질의에 잡힌다.

    Attributes:
        date_from: 촬영 시각 하한 — SQLite datetime() 비교 가능 문자열.
        date_to: 촬영 시각 상한 — 동일 포맷.
        countries: 국가명 부분 일치(OR). photos.country는 한국어 지명.
        cities: 장소명 부분 일치(OR) — city·district 양쪽을 매칭한다
            ("일산"은 district "일산서구"에 있음).
        trip_ids: trip 정확 일치(IN) — countries·cities와 OR로 결합되는
            장소 스코프 (지명 → trip 도출 경로, prd §6-c).
        caption_match: 캡션 본문 부분 일치 — 캡션은 영어(D19).
        trip_id: trip 정확 일치 — 직접 지정용 독립(AND) 조건.
    """

    date_from: str | None = None
    date_to: str | None = None
    countries: tuple[str, ...] = ()
    cities: tuple[str, ...] = ()
    trip_ids: tuple[str, ...] = ()
    caption_match: str | None = None
    trip_id: str | None = None


@dataclass(frozen=True)
class DedupReport:
    """cross-source dedup 재계산 결과 — apply_cross_source_dedup 반환.

    Attributes:
        groups: 소스 2개 이상이 공유한 content_hash 그룹 수.
        marked: duplicate_of가 기록된 사진 수.
    """

    groups: int
    marked: int


@dataclass(frozen=True)
class GeocodeCacheEntry:
    """양자화 셀의 캐시된 reverse geocode 결과 — get_geocode_cache 반환.

    바다 등 주소 없는 좌표의 negative 결과도 전 필드 None으로 캐시돼 재요청을
    막는다(엔트리 자체는 존재 — 캐시 미스의 None과 구분된다).

    Attributes:
        country: 국가명(한국어 표기). 주소 없으면 None.
        city: 시/도명. 없으면 None.
        district: 구/동명. 없으면 None.
        country_code: ISO 3166-1 alpha-2 대문자. 백필 전이거나 없으면 None.
    """

    country: str | None
    city: str | None
    district: str | None
    country_code: str | None


@dataclass(frozen=True)
class DailyRadiusArea:
    """저장된 Daily Radius 영역 한 건 — list_daily_radius_areas 반환.

    Attributes:
        label: 사용자 지정 라벨(예: ``집``, ``직장``).
        center_lat: 중심 위도.
        center_lng: 중심 경도.
        radius_km: 반경(km).
    """

    label: str
    center_lat: float
    center_lng: float
    radius_km: float


@dataclass(frozen=True)
class IndexingStats:
    """부분 인덱싱 진행 수치 — indexing_stats 반환 (PLAN §6).

    분모·분자 모두 영상·duplicate를 제외해 질의 레이어 노출 모집단과 일치한다.

    Attributes:
        ready: 검색 가능 사진 수(caption_done·trip_assigned).
        total: 인덱싱 대상 전체 수.
    """

    ready: int
    total: int


@dataclass(frozen=True)
class GpsPoint:
    """지도용 GPS 점 한 개 — exposed_gps_points 반환 (ADR-0009 §3).

    좌표는 "내 서버 → 내 브라우저" 노출이 허용된 로컬 필드다.

    Attributes:
        photo_id: 사진 식별자.
        latitude: GPS 위도.
        longitude: GPS 경도.
        date: KST 달력일(``YYYY-MM-DD``) — taken_at 앞 10자.
    """

    photo_id: str
    latitude: float
    longitude: float
    date: str


@dataclass(frozen=True)
class PhotoOnDate:
    """특정 KST 달력일의 노출 사진 한 건 — exposed_photos_by_date 반환 (ADR-0009 §3).

    날짜 상세 그리드용 — GPS 없는 사진(latitude None)도 포함된다. 좌표는 로컬
    노출 허용 필드다. 필드 순서는 by-date JSON 응답 키 순서와 일치한다.

    Attributes:
        photo_id: 사진 식별자.
        taken_at: 촬영 시각(KST aware ISO).
        latitude: GPS 위도. 없으면 None.
        longitude: GPS 경도. 없으면 None.
        country: 한국어 국가명(geocode). 없으면 None.
        city: 한국어 시/도명. 없으면 None.
    """

    photo_id: str
    taken_at: str | None
    latitude: float | None
    longitude: float | None
    country: str | None
    city: str | None


@dataclass(frozen=True)
class NoLocationDayGroup:
    """위치 미상 사진의 KST 일별 그룹 한 건 — no_location_day_groups 반환 (prd §6-b).

    수동 지오코딩 드로어 입력 — date 내림차순 목록의 한 그룹이다.

    Attributes:
        date: KST 달력일(``YYYY-MM-DD``).
        count: 그룹의 위치 미상 사진 수.
        sample_photo_ids: 대표 사진 id(taken_at순 ≤4).
        trip_name: 그룹 내 최빈 trip의 이름. 없으면 None.
    """

    date: str
    count: int
    sample_photo_ids: tuple[str, ...]
    trip_name: str | None


class EddrDatabase:
    """SQLite 파일 기반 EDDR 저장소 접근 계층.

    photos, captions, embeddings, index_errors 테이블을 관리하며
    각 연산마다 새 Connection을 열고 닫는다.

    Attributes:
        path: SQLite 데이터베이스 파일 경로.
    """

    def __init__(self, path: Path | str):
        """저장소 핸들을 만든다 — 실제 파일·스키마 생성은 initialize() 시점.

        Args:
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

                CREATE TABLE IF NOT EXISTS trips (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    start_at TEXT NOT NULL,
                    end_at TEXT NOT NULL,
                    photo_count INTEGER NOT NULL DEFAULT 0,
                    center_lat REAL,
                    center_lng REAL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS trip_countries (
                    trip_id TEXT NOT NULL,
                    country_code TEXT NOT NULL,
                    PRIMARY KEY(trip_id, country_code),
                    FOREIGN KEY(trip_id) REFERENCES trips(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS daily_radius_areas (
                    id INTEGER PRIMARY KEY,
                    label TEXT NOT NULL,
                    center_lat REAL NOT NULL,
                    center_lng REAL NOT NULL,
                    radius_km REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS geocode_cache (
                    lat_quantized INTEGER NOT NULL,
                    lng_quantized INTEGER NOT NULL,
                    country TEXT,
                    city TEXT,
                    district TEXT,
                    source TEXT NOT NULL DEFAULT 'nominatim',
                    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(lat_quantized, lng_quantized)
                );

                -- 사진 메모 — 사진별 1메모, photo_id PK (D26 M5, prd §6-d).
                CREATE TABLE IF NOT EXISTS notes (
                    photo_id TEXT PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
                    text TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._migrate_photos_columns(conn)
            self._migrate_geocode_cache_columns(conn)
            self._migrate_captions_fts(conn)

    @staticmethod
    def _migrate_photos_columns(conn: sqlite3.Connection) -> None:
        """photos 테이블에 누락된 enrichment 컬럼을 멱등하게 추가한다.

        운영 DB는 ALTER 경로로, 신규 DB도 같은 경로로 수렴한다 — 컬럼 정의의
        단일 출처를 이 목록 하나로 유지한다.
        """
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(photos)")}
        for name, ddl in (
            ("country", "country TEXT"),
            ("city", "city TEXT"),
            ("district", "district TEXT"),
            ("trip_id", "trip_id TEXT REFERENCES trips(id) ON DELETE SET NULL"),
            ("duplicate_of", "duplicate_of TEXT REFERENCES photos(id)"),
            ("taken_at_raw", "taken_at_raw TEXT"),
            # NULL = EXIF 유래 좌표, 'manual' = 수동 지오코딩(ADR-0009 §4, prd §6-d).
            ("location_source", "location_source TEXT"),
        ):
            if name not in existing:
                conn.execute(f"ALTER TABLE photos ADD COLUMN {ddl}")

    @staticmethod
    def _migrate_geocode_cache_columns(conn: sqlite3.Connection) -> None:
        """geocode_cache에 누락된 컬럼을 멱등하게 추가한다.

        country_code(ISO 3166-1 alpha-2 대문자)는 trip_countries 산출용 —
        ④ 운영 DB는 이 컬럼 없이 생성돼 ALTER 경로로 수렴한다(⑥에서 백필).
        """
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(geocode_cache)")}
        if "country_code" not in existing:
            conn.execute("ALTER TABLE geocode_cache ADD COLUMN country_code TEXT")

    @staticmethod
    def _migrate_captions_fts(conn: sqlite3.Connection) -> None:
        """captions의 FTS5(BM25) 인덱스와 동기화 트리거를 멱등 생성한다.

        external-content 방식이라 텍스트는 captions가 단일 소유하고, 행 수
        불일치(최초 마이그레이션·드리프트) 시에만 rebuild로 재색인한다.
        porter 토크나이저 — 캡션이 영어(D19)라 어간 매칭이 유효하다.
        """
        conn.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS captions_fts USING fts5(
                text,
                content='captions',
                content_rowid='rowid',
                tokenize='porter unicode61'
            );
            CREATE TRIGGER IF NOT EXISTS captions_fts_ai AFTER INSERT ON captions BEGIN
                INSERT INTO captions_fts(rowid, text) VALUES (new.rowid, new.text);
            END;
            CREATE TRIGGER IF NOT EXISTS captions_fts_ad AFTER DELETE ON captions BEGIN
                INSERT INTO captions_fts(captions_fts, rowid, text)
                VALUES ('delete', old.rowid, old.text);
            END;
            CREATE TRIGGER IF NOT EXISTS captions_fts_au AFTER UPDATE ON captions BEGIN
                INSERT INTO captions_fts(captions_fts, rowid, text)
                VALUES ('delete', old.rowid, old.text);
                INSERT INTO captions_fts(rowid, text) VALUES (new.rowid, new.text);
            END;
            """
        )
        captions_n = conn.execute("SELECT count(*) FROM captions").fetchone()[0]
        # external-content FTS의 count(*)는 content 테이블을 비춰 항상 일치해 보인다 —
        # 실색인 행 수는 docsize shadow 테이블로 세야 누락(최초 마이그레이션)을 잡는다.
        fts_n = conn.execute("SELECT count(*) FROM captions_fts_docsize").fetchone()[0]
        if captions_n != fts_n:
            conn.execute("INSERT INTO captions_fts(captions_fts) VALUES('rebuild')")

    def upsert_photo(self, photo: PhotoRecord) -> None:
        """PhotoRecord를 photos 테이블에 삽입하거나 갱신한다.

        id 충돌 시 source_uri·content_hash 등 메타 필드를 덮어쓰고
        updated_at을 현재 시각으로 갱신한다. 단 indexing_status는
        기존 행이 vision 이후 단계(caption_done·trip_assigned·skipped_video)면
        보존한다 — 재적재(meta_done)가 파이프라인 진행 상태를 리셋하지 않도록.
        location_source='manual'인 행은 좌표도 보존한다(ADR-0009 §4) —
        소스 레코드의 GPS(대개 NULL)가 사용자 수동 지정을 조용히 덮지 않도록.
        사용자 의도 우선: 이후 소스에 EXIF GPS가 생겨도 manual이 이긴다.

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
                    latitude = CASE
                        WHEN photos.location_source = 'manual'
                        THEN photos.latitude ELSE excluded.latitude
                    END,
                    longitude = CASE
                        WHEN photos.location_source = 'manual'
                        THEN photos.longitude ELSE excluded.longitude
                    END,
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

    def upsert_note(self, photo_id: str, text: str) -> None:
        """사진 메모를 삽입하거나 갱신한다 — 사진별 1메모 (D26 M5, prd §6-d).

        Args:
            photo_id: 대상 사진의 식별자 (PK — 충돌 시 text·updated_at 갱신).
            text: 메모 본문 (한국어 자유 텍스트).
        """
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notes(photo_id, text) VALUES (?, ?)
                ON CONFLICT(photo_id) DO UPDATE SET
                    text = excluded.text,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (photo_id, text),
            )

    def get_note(self, photo_id: str) -> str | None:
        """사진 메모 본문을 반환한다. 메모가 없으면 None."""
        with self.connect() as conn:
            row = conn.execute("SELECT text FROM notes WHERE photo_id = ?", (photo_id,)).fetchone()
        return row["text"] if row else None

    def list_notes(self) -> list[tuple[str, str]]:
        """사진 메모 전체를 photo_id 순서로 반환한다 — 검색 인덱스 빌드용 read-only 경로."""
        with self.connect() as conn:
            rows = conn.execute("SELECT photo_id, text FROM notes ORDER BY photo_id").fetchall()
        return [(row["photo_id"], row["text"]) for row in rows]

    def delete_note(self, photo_id: str) -> bool:
        """사진 메모를 삭제한다.

        Returns:
            삭제된 행이 있으면 True — 없던 메모면 False (라우트 404 분기용).
        """
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM notes WHERE photo_id = ?", (photo_id,))
            return cursor.rowcount > 0

    def embedding_vector_ids(self, photo_id: str, kind: str) -> list[str]:
        """사진·종류별 임베딩 vector_id 목록 — 벡터 스토어 삭제 입력용 (D26 M5)."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT vector_id FROM embeddings WHERE photo_id = ? AND kind = ?",
                (photo_id, kind),
            ).fetchall()
        return [row["vector_id"] for row in rows]

    def delete_embedding_records(self, photo_id: str, kind: str) -> None:
        """사진·종류별 임베딩 레코드를 삭제한다 — 메모 삭제 경로 (D26 M5).

        같은 kind의 전 model_id 행을 지운다. 다른 kind(caption_text)는 비파괴.
        """
        with self.connect() as conn:
            conn.execute("DELETE FROM embeddings WHERE photo_id = ? AND kind = ?", (photo_id, kind))

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

    def prune_index_errors(self) -> int:
        """산출물이 이미 존재하는 사진의 index_errors 행을 삭제한다 — 잔존 기록 정리.

        재시도 성공 후에도 남는 에러 기록을 멱등하게 정리한다. 산출물 조건이
        명확한 stage만 대상: ``vision``(캡션 존재)·``geocode``(country 충전).
        reader가 없어 삭제가 안전하다(마킹 대신 삭제). photo_id가 없는
        stage(manual_location 등)는 사진 단위 reconcile이 불가하므로 보존한다.

        Returns:
            삭제된 행 수.
        """
        with self.connect() as conn:
            cur = conn.execute(
                """
                DELETE FROM index_errors
                WHERE (stage = 'vision'
                       AND photo_id IN (SELECT photo_id FROM captions))
                   OR (stage = 'geocode'
                       AND photo_id IN (SELECT id FROM photos WHERE country IS NOT NULL))
                """
            )
            return cur.rowcount

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

    def photos_missing_hashes(self, limit: int | None = None) -> list[PhotoRecord]:
        """해시 백필 대상 사진을 반환한다.

        이미지 파일이 있고 영상(skipped_video)이 아니며 content_hash 또는
        perceptual_hash가 비어 있는 행이 대상이다.

        Args:
            limit: 반환할 최대 레코드 수. None이면 전체.

        Returns:
            id 순으로 정렬된 PhotoRecord 리스트.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*
                FROM photos p
                WHERE p.image_path IS NOT NULL
                  AND p.indexing_status != 'skipped_video'
                  AND (p.content_hash IS NULL OR p.perceptual_hash IS NULL)
                ORDER BY p.id
                LIMIT ?
                """,
                (-1 if limit is None else limit,),
            ).fetchall()
        return [_row_to_photo(r) for r in rows]

    def update_photo_hashes(
        self,
        photo_id: str,
        content_hash: str | None = None,
        perceptual_hash: str | None = None,
    ) -> None:
        """사진의 해시 필드를 갱신한다. None으로 전달된 필드는 기존 값을 유지한다.

        Args:
            photo_id: 대상 사진의 식별자.
            content_hash: 새 BLAKE3 해시. None이면 미변경.
            perceptual_hash: 새 dHash. None이면 미변경.
        """
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE photos SET
                    content_hash = COALESCE(?, content_hash),
                    perceptual_hash = COALESCE(?, perceptual_hash),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (content_hash, perceptual_hash, photo_id),
            )

    def apply_cross_source_dedup(self, source_priority: tuple[str, ...]) -> DedupReport:
        """duplicate_of를 전체 재계산한다 — 기존 마킹을 지우고 다시 마킹한다.

        content_hash를 2개 이상 소스가 공유하는 그룹에서 source_priority 순
        (동순위는 id 사전순) 첫 행을 canonical로 정하고, canonical과 source가
        다른 행에만 duplicate_of를 기록한다. canonical과 같은 소스의 형제 행은
        마킹하지 않는다 (ADR-0002: dedup은 cross-source만).

        Args:
            source_priority: canonical 선택 우선순위 소스 튜플.

        Returns:
            cross-source 그룹 수와 마킹된 행 수를 담은 DedupReport.
        """
        priority_case = " ".join(f"WHEN ? THEN {rank}" for rank in range(len(source_priority)))
        # sqlite3 드라이버는 WITH 절로 시작하는 UPDATE의 rowcount를 -1로 반환하므로
        # 변경 행 수는 SQLite changes()로 읽는다.
        with self.connect() as conn:
            conn.execute(
                "UPDATE photos SET duplicate_of = NULL, updated_at = CURRENT_TIMESTAMP"
                " WHERE duplicate_of IS NOT NULL"
            )
            groups = int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT content_hash
                        FROM photos
                        WHERE content_hash IS NOT NULL
                        GROUP BY content_hash
                        HAVING COUNT(DISTINCT source) > 1
                    )
                    """
                ).fetchone()[0]
            )
            conn.execute(
                f"""
                WITH dup_groups AS (
                    SELECT content_hash
                    FROM photos
                    WHERE content_hash IS NOT NULL
                    GROUP BY content_hash
                    HAVING COUNT(DISTINCT source) > 1
                ),
                canonical AS (
                    SELECT content_hash, id AS canonical_id, source AS canonical_source
                    FROM (
                        SELECT p.content_hash, p.id, p.source,
                               ROW_NUMBER() OVER (
                                   PARTITION BY p.content_hash
                                   ORDER BY CASE p.source {priority_case} ELSE 99 END, p.id
                               ) AS rn
                        FROM photos p
                        JOIN dup_groups g ON g.content_hash = p.content_hash
                    )
                    WHERE rn = 1
                )
                UPDATE photos SET
                    duplicate_of = (
                        SELECT c.canonical_id FROM canonical c
                        WHERE c.content_hash = photos.content_hash
                    ),
                    updated_at = CURRENT_TIMESTAMP
                WHERE EXISTS (
                    SELECT 1 FROM canonical c
                    WHERE c.content_hash = photos.content_hash
                      AND c.canonical_source != photos.source
                )
                """,
                source_priority,
            )
            marked = int(conn.execute("SELECT changes()").fetchone()[0])
        return DedupReport(groups=groups, marked=marked)

    def photos_needing_geocode(self, limit: int | None = None) -> list[PhotoRecord]:
        """GPS는 있으나 country가 비어 있는 사진을 좌표순으로 반환한다.

        좌표순 정렬은 같은 양자화 셀의 사진을 연속 배치해 캐시 적중을 모은다.

        Args:
            limit: 반환할 최대 레코드 수. None이면 전체.

        Returns:
            PhotoRecord 리스트.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*
                FROM photos p
                WHERE p.latitude IS NOT NULL
                  AND p.longitude IS NOT NULL
                  AND p.country IS NULL
                ORDER BY p.latitude, p.longitude, p.id
                LIMIT ?
                """,
                (-1 if limit is None else limit,),
            ).fetchall()
        return [_row_to_photo(r) for r in rows]

    def get_geocode_cache(self, lat_quantized: int, lng_quantized: int) -> GeocodeCacheEntry | None:
        """양자화 셀의 캐시된 geocode 결과를 GeocodeCacheEntry로 반환한다. 미스면 None.

        주소 없는 좌표(바다 등)의 negative 결과도 전 필드 None인 엔트리로
        캐시돼 있어 재요청을 막는다(캐시 미스의 None과 구분된다).
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT country, city, district, country_code FROM geocode_cache"
                " WHERE lat_quantized = ? AND lng_quantized = ?",
                (lat_quantized, lng_quantized),
            ).fetchone()
        if row is None:
            return None
        return GeocodeCacheEntry(
            country=row["country"],
            city=row["city"],
            district=row["district"],
            country_code=row["country_code"],
        )

    def upsert_geocode_cache(
        self,
        lat_quantized: int,
        lng_quantized: int,
        country: str | None,
        city: str | None,
        district: str | None,
        country_code: str | None,
    ) -> None:
        """양자화 셀의 reverse geocoding 결과를 캐시한다."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO geocode_cache(
                    lat_quantized, lng_quantized, country, city, district, country_code
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(lat_quantized, lng_quantized) DO UPDATE SET
                    country = excluded.country,
                    city = excluded.city,
                    district = excluded.district,
                    country_code = excluded.country_code,
                    fetched_at = CURRENT_TIMESTAMP
                """,
                (lat_quantized, lng_quantized, country, city, district, country_code),
            )

    def geocode_cells_missing_country_code(self) -> list[tuple[int, int]]:
        """country는 있으나 country_code가 빈 캐시 셀을 반환한다 — ISO 백필 대상.

        negative cache(country IS NULL — 바다 등)는 재조회해도 코드가 없으므로 제외한다.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT lat_quantized, lng_quantized FROM geocode_cache
                WHERE country IS NOT NULL AND country_code IS NULL
                ORDER BY lat_quantized, lng_quantized
                """
            ).fetchall()
        return [(row["lat_quantized"], row["lng_quantized"]) for row in rows]

    def update_geocode_cache_country_code(
        self, lat_quantized: int, lng_quantized: int, country_code: str | None
    ) -> None:
        """캐시 셀의 country_code만 갱신한다 — 백필 전용(지명 필드는 보존)."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE geocode_cache SET country_code = ?"
                " WHERE lat_quantized = ? AND lng_quantized = ?",
                (country_code, lat_quantized, lng_quantized),
            )

    def update_photo_geo(
        self,
        photo_id: str,
        country: str | None,
        city: str | None,
        district: str | None,
    ) -> None:
        """사진의 행정구역 필드를 갱신한다.

        Args:
            photo_id: 대상 사진의 식별자.
            country: 국가명. None이면 NULL로 기록된다 (주소 없는 좌표).
            city: 시 단위 행정구역명.
            district: 구/동 단위 행정구역명.
        """
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE photos SET
                    country = ?, city = ?, district = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (country, city, district, photo_id),
            )

    def gps_coordinates(self, exclude_duplicates: bool = True) -> list[tuple[float, float]]:
        """GPS 좌표 목록을 반환한다 — Daily Radius 밀도 추정 입력.

        Args:
            exclude_duplicates: True면 duplicate_of가 찍힌 행을 제외해
                cross-source 중복의 이중 계산을 막는다.

        Returns:
            (latitude, longitude) 튜플 리스트.
        """
        where = "p.latitude IS NOT NULL AND p.longitude IS NOT NULL"
        if exclude_duplicates:
            where += " AND p.duplicate_of IS NULL"
        with self.connect() as conn:
            rows = conn.execute(f"SELECT p.latitude, p.longitude FROM photos p WHERE {where}")
            return [(row["latitude"], row["longitude"]) for row in rows]

    def majority_place_near(self, lat: float, lng: float, radius_km: float) -> str | None:
        """좌표 주변 사진의 최빈 (city, district) 표시 문자열을 반환한다.

        wizard 후보 라벨링 보조용 — 반경을 위경도 bbox로 근사한다.

        Args:
            lat: 중심 위도.
            lng: 중심 경도.
            radius_km: 근사 반경(km).

        Returns:
            "city district" 형식 문자열 (한쪽만 있으면 그것만), 없으면 None.
        """
        d_lat = radius_km / 111.0
        d_lng = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT city, district, COUNT(*) AS n
                FROM photos
                WHERE latitude BETWEEN ? AND ?
                  AND longitude BETWEEN ? AND ?
                  AND (city IS NOT NULL OR district IS NOT NULL)
                GROUP BY city, district
                ORDER BY n DESC
                LIMIT 1
                """,
                (lat - d_lat, lat + d_lat, lng - d_lng, lng + d_lng),
            ).fetchone()
        if row is None:
            return None
        parts = [part for part in (row["city"], row["district"]) if part]
        return " ".join(parts) if parts else None

    def replace_daily_radius_areas(self, areas: list[tuple[str, float, float, float]]) -> None:
        """daily_radius_areas를 전체 교체한다 — wizard 재실행이 멱등하도록.

        Args:
            areas: (label, center_lat, center_lng, radius_km) 튜플 리스트.
        """
        with self.connect() as conn:
            conn.execute("DELETE FROM daily_radius_areas")
            conn.executemany(
                "INSERT INTO daily_radius_areas(label, center_lat, center_lng, radius_km)"
                " VALUES (?, ?, ?, ?)",
                areas,
            )

    def list_daily_radius_areas(self) -> list[DailyRadiusArea]:
        """저장된 Daily Radius 영역을 DailyRadiusArea 리스트로 반환한다."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT label, center_lat, center_lng, radius_km"
                " FROM daily_radius_areas ORDER BY id"
            ).fetchall()
        return [
            DailyRadiusArea(
                label=row["label"],
                center_lat=row["center_lat"],
                center_lng=row["center_lng"],
                radius_km=row["radius_km"],
            )
            for row in rows
        ]

    def photos_for_trip_clustering(self) -> list[PhotoRecord]:
        """trip 세그멘테이션 입력 사진을 촬영 시각 순으로 반환한다.

        GPS·촬영 시각이 모두 있고 영상이 아닌 행이 대상이다(영상 완전 제외 —
        사용자 결정 2026-06-11). 소스별 taken_at 포맷이 섞여 있어(aware/naive)
        정렬은 SQLite datetime() 정규화(UTC 변환·naive)로 한다.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.*
                FROM photos p
                WHERE p.latitude IS NOT NULL
                  AND p.longitude IS NOT NULL
                  AND p.taken_at IS NOT NULL
                  AND p.indexing_status != 'skipped_video'
                ORDER BY datetime(p.taken_at), p.id
                """
            ).fetchall()
        return [_row_to_photo(r) for r in rows]

    def insert_trip(
        self,
        trip_id: str,
        name: str,
        start_at: str,
        end_at: str,
        center_lat: float | None,
        center_lng: float | None,
    ) -> None:
        """trips 행을 삽입한다. photo_count는 finalize_trip_photo_counts가 채운다.

        Args:
            trip_id: 결정적 trip 식별자 (예: ``trip_20190601_01``).
            name: 자동 생성 이름 (예: ``강릉시 여행 2019-06``).
            start_at: 시작 시각 — naive UTC ``YYYY-MM-DD HH:MM:SS``.
            end_at: 끝 시각 — 동일 포맷.
            center_lat: 구간 사진 평균 위도.
            center_lng: 구간 사진 평균 경도.
        """
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO trips(id, name, start_at, end_at, center_lat, center_lng)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (trip_id, name, start_at, end_at, center_lat, center_lng),
            )

    def insert_trip_countries(self, trip_id: str, country_codes: list[str]) -> None:
        """trip의 방문 국가 ISO 코드를 기록한다 (D14 다국가 M2M)."""
        with self.connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO trip_countries(trip_id, country_code) VALUES (?, ?)",
                [(trip_id, code) for code in country_codes],
            )

    def assign_trip_by_timerange(self, trip_id: str, start_at: str, end_at: str) -> int:
        """기간 내 사진에 trip_id를 배정하고 caption_done만 trip_assigned로 전이한다.

        세그먼트는 복귀(in 사진)에서 끊기므로 [start_at, end_at] 사이의 GPS 사진은
        전부 해당 run 소속이고, GPS 없는 사진도 시간만 맞으면 함께 배정된다
        (PLAN §8 "시간만 있으면 trip에 포함"). 영상은 배정하지 않는다.
        caption_done 이전 단계(meta_done 등)는 trip_id만 받고 status를 유지해
        파이프라인 체크포인트 의미를 보존한다.

        Args:
            trip_id: 배정할 trip 식별자.
            start_at: 구간 시작 — naive UTC ``YYYY-MM-DD HH:MM:SS``.
            end_at: 구간 끝 — 동일 포맷.

        Returns:
            trip_id가 배정된 행 수.
        """
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE photos SET
                    trip_id = ?,
                    indexing_status = CASE
                        WHEN indexing_status = 'caption_done' THEN 'trip_assigned'
                        ELSE indexing_status
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE taken_at IS NOT NULL
                  AND indexing_status != 'skipped_video'
                  AND datetime(taken_at) BETWEEN datetime(?) AND datetime(?)
                """,
                (trip_id, start_at, end_at),
            )
            return int(conn.execute("SELECT changes()").fetchone()[0])

    def reset_trip_assignments(self) -> None:
        """trip 배정을 전부 되돌린다 — 재클러스터가 멱등하도록.

        trip_assigned는 caption_done으로 복원하고(전이의 역), trip_id를 비운 뒤
        trips를 비운다(trip_countries는 FK CASCADE).
        """
        with self.connect() as conn:
            conn.execute(
                "UPDATE photos SET indexing_status = 'caption_done',"
                " updated_at = CURRENT_TIMESTAMP WHERE indexing_status = 'trip_assigned'"
            )
            conn.execute(
                "UPDATE photos SET trip_id = NULL, updated_at = CURRENT_TIMESTAMP"
                " WHERE trip_id IS NOT NULL"
            )
            conn.execute("DELETE FROM trips")

    def finalize_trip_photo_counts(self) -> None:
        """trips.photo_count를 질의 레이어 노출 기준으로 갱신한다.

        배정 행 중 duplicate_of IS NULL만 센다 — ⑦이 노출할 사진 수와 일치
        (영상은 배정 자체가 없다).
        """
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE trips SET photo_count = (
                    SELECT COUNT(*) FROM photos
                    WHERE photos.trip_id = trips.id AND photos.duplicate_of IS NULL
                )
                """
            )

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

    def get_latest_captions_for_ids(self, photo_ids: list[str]) -> dict[str, str]:
        """여러 사진의 가장 최근 캡션을 한 번의 쿼리로 조회한다 — get_latest_caption 배치판.

        검색 응답 조립의 N+1(사진당 캡션 1쿼리)을 제거한다. 사진당 generated_at
        내림차순 1행만 취해 단건 get_latest_caption과 동일한 캡션을 돌려준다.

        Args:
            photo_ids: 조회할 사진 식별자 목록.

        Returns:
            photo_id → 최신 캡션 텍스트 매핑. 캡션 없는 id는 키가 없다.
        """
        if not photo_ids:
            return {}
        placeholders = ",".join("?" * len(photo_ids))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT photo_id, text
                FROM (
                    SELECT
                        photo_id,
                        text,
                        ROW_NUMBER() OVER (
                            PARTITION BY photo_id ORDER BY generated_at DESC
                        ) AS rn
                    FROM captions
                    WHERE photo_id IN ({placeholders})
                )
                WHERE rn = 1
                """,
                (*photo_ids,),
            ).fetchall()
        return {str(row["photo_id"]): str(row["text"]) for row in rows}

    def search_caption_photo_ids(self, match: str, limit: int) -> list[str]:
        """캡션 FTS5 BM25 매칭 photo_id를 관련도순으로 반환한다 — lexical leg.

        Args:
            match: FTS5 MATCH 식 (구는 큰따옴표 인용 — 조립은 호출 측 책임).
            limit: 최대 반환 수.

        Returns:
            photo_id 리스트 — 사진당 최고 점수 기준 bm25 오름차순(관련도 내림차순).
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                -- bm25()는 순수 FTS 질의 컨텍스트에서만 허용 — 플래트닝되면
                -- JOIN·집계 컨텍스트로 합쳐져 오류라 MATERIALIZED로 배리어를 친다.
                WITH f AS MATERIALIZED (
                    SELECT rowid AS rid, bm25(captions_fts) AS score
                    FROM captions_fts
                    WHERE captions_fts MATCH ?
                )
                SELECT c.photo_id AS photo_id, MIN(f.score) AS best
                FROM f
                JOIN captions c ON c.rowid = f.rid
                GROUP BY c.photo_id
                ORDER BY best, c.photo_id
                LIMIT ?
                """,
                (match, limit),
            ).fetchall()
        return [row["photo_id"] for row in rows]

    def count_caption_matches(self, match: str) -> int:
        """캡션 FTS5 MATCH 식에 걸리는 고유 photo_id 수를 반환한다.

        검색 품질 감사에서 ``food``처럼 너무 넓은 키워드의 문서 빈도를 확인하는
        용도다. 순위가 필요 없으므로 BM25를 계산하지 않는다.
        """
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT c.photo_id) AS count
                FROM captions_fts f
                JOIN captions c ON c.rowid = f.rowid
                WHERE captions_fts MATCH ?
                """,
                (match,),
            ).fetchone()
        return int(row["count"] if row else 0)

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

    # ── 질의 레이어(⑦) 전용 — 모든 사진 응답은 duplicate_of IS NULL만 노출(PLAN §4.2) ──

    def query_photos(self, filters: PhotoQueryFilters, limit: int) -> list[PhotoRecord]:
        """필터 조건에 맞는 사진을 반환한다 — search_photos tool의 데이터 경로.

        dedup(duplicate_of IS NULL)·영상 제외를 강제하고, geocode 있는 사진을
        앞에 배치한다(장소 질의의 GPS 무 사진 분리 — 사용자 제안 2026-06-10).
        trip 내 조회는 시간 오름차순, 그 외는 최신순이다.

        Args:
            filters: 적용할 필터.
            limit: 반환할 최대 레코드 수 (context overflow 차단 — ADR-0003).

        Returns:
            PhotoRecord 리스트.
        """
        clauses, params = _photo_filter_sql(filters)
        time_order = "datetime(p.taken_at)" + ("" if filters.trip_id else " DESC")
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT p.* FROM photos p
                WHERE {" AND ".join(clauses)}
                ORDER BY (p.country IS NULL), {time_order}, p.id
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [_row_to_photo(r) for r in rows]

    def filter_photo_ids(self, photo_ids: list[str], filters: PhotoQueryFilters) -> list[str]:
        """주어진 사진 id 중 필터(+dedup·영상 제외)를 통과하는 id만 입력 순서대로 반환한다.

        semantic_search_photos의 후처리 경로 — Chroma 메타데이터에는 geocode·날짜가
        없으므로 over-fetch한 후보를 SQL 측에서 거른다.

        Args:
            photo_ids: 거리순으로 정렬된 후보 사진 id 목록.
            filters: 적용할 필터.

        Returns:
            필터를 통과한 id 목록 (입력 순서 보존).
        """
        if not photo_ids:
            return []
        clauses, params = _photo_filter_sql(filters)
        placeholders = ",".join("?" * len(photo_ids))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT p.id FROM photos p WHERE p.id IN ({placeholders})"
                f" AND {' AND '.join(clauses)}",
                (*photo_ids, *params),
            ).fetchall()
        passed = {row["id"] for row in rows}
        return [photo_id for photo_id in photo_ids if photo_id in passed]

    def query_trips(
        self,
        countries: tuple[str, ...] = (),
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
    ) -> list[TripRecord]:
        """필터 조건에 맞는 trip을 최신 시작순으로 반환한다 — list_trips tool의 데이터 경로.

        국가 필터는 trip 이름 또는 소속 사진의 한국어 국가명(photos.country)
        부분 일치로 매칭한다(trip_countries는 ISO 코드라 한국어 질의와 직접
        매칭 불가). 날짜 범위는 trip 기간과의 겹침으로 판정한다.

        Args:
            countries: 국가명 부분 일치(OR).
            date_from: 이 시각 이후에 끝난 trip만.
            date_to: 이 시각 이전에 시작한 trip만.
            limit: 반환할 최대 레코드 수.

        Returns:
            TripRecord 리스트.
        """
        clauses: list[str] = ["1=1"]
        params: list[object] = []
        if countries:
            ors = " OR ".join(
                "(t.name LIKE '%' || ? || '%' OR EXISTS ("
                " SELECT 1 FROM photos p WHERE p.trip_id = t.id"
                " AND p.country LIKE '%' || ? || '%'))"
                for _ in countries
            )
            clauses.append(f"({ors})")
            for country in countries:
                params.extend([country, country])
        if date_from:
            clauses.append("datetime(t.end_at) >= datetime(?)")
            params.append(date_from)
        if date_to:
            clauses.append("datetime(t.start_at) <= datetime(?)")
            params.append(date_to)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT t.* FROM trips t
                WHERE {" AND ".join(clauses)}
                ORDER BY datetime(t.start_at) DESC, t.id
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [_row_to_trip(r) for r in rows]

    def trip_ids_for_places(
        self, countries: tuple[str, ...] = (), cities: tuple[str, ...] = ()
    ) -> list[str]:
        """추출 지명에 매칭되는 사진이 속한 DISTINCT trip_id를 반환한다 (prd §6-c).

        photos의 한국어 지명을 직접 매칭하므로 ISO 코드 매핑이 필요 없는
        자기일관 방식이다 — 필터(_photo_filter_sql)와 동일한 매칭 의미론을
        공유한다. 도출된 trip_id는 장소 OR 그룹(PhotoQueryFilters.trip_ids)에
        넣어 GPS 무 사진을 trip 소속으로 건진다.

        Args:
            countries: 한국어 국가명 부분 일치(OR).
            cities: 한국어 장소명 부분 일치(OR) — city·district 양쪽.

        Returns:
            trip_id 사전순 리스트. 지명이 모두 비면 빈 리스트.
        """
        ors, params = _place_match_sql(countries, cities)
        if not ors:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT DISTINCT p.trip_id FROM photos p
                WHERE p.trip_id IS NOT NULL AND ({" OR ".join(ors)})
                ORDER BY p.trip_id
                """,
                params,
            ).fetchall()
        return [row["trip_id"] for row in rows]

    def get_trip_record(self, trip_id: str) -> TripRecord | None:
        """trip_id로 단일 trip 레코드를 조회한다. 없으면 None."""
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
        return _row_to_trip(row) if row else None

    def trip_country_codes(self, trip_id: str) -> list[str]:
        """trip의 방문 국가 ISO 코드를 사전순으로 반환한다."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT country_code FROM trip_countries WHERE trip_id = ? ORDER BY country_code",
                (trip_id,),
            ).fetchall()
        return [row["country_code"] for row in rows]

    def trip_top_cities(self, trip_id: str, top_n: int = 5) -> list[str]:
        """trip 소속 사진의 최빈 city를 반환한다 — get_trip 상세의 방문 도시 요약용."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT city, COUNT(*) AS n FROM photos
                WHERE trip_id = ? AND city IS NOT NULL AND duplicate_of IS NULL
                GROUP BY city ORDER BY n DESC, city
                LIMIT ?
                """,
                (trip_id, top_n),
            ).fetchall()
        return [row["city"] for row in rows]

    def indexing_stats(self) -> IndexingStats:
        """검색 가능·전체 사진 수를 IndexingStats로 반환한다 — 부분 인덱싱 UX(PLAN §6).

        검색 가능 = caption_done·trip_assigned. 분모·분자 모두 영상과
        duplicate를 제외해 질의 레이어가 노출하는 모집단과 일치시킨다.
        """
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    SUM(indexing_status IN ('caption_done', 'trip_assigned')) AS ready,
                    COUNT(*) AS total
                FROM photos
                WHERE indexing_status != 'skipped_video' AND duplicate_of IS NULL
                """
            ).fetchone()
        return IndexingStats(ready=int(row["ready"] or 0), total=int(row["total"] or 0))

    def indexing_stage_counts(self) -> dict[str, int]:
        """indexing_status별 사진 수 — /api/status 단계 분해용 (FR-STATUS-1).

        indexing_stats()와 달리 영상·duplicate 제외 필터를 걸지 않는다 —
        단계별 진행 분포를 원시 그대로 보여주는 것이 목적이다.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT indexing_status AS stage, COUNT(*) AS n
                FROM photos GROUP BY indexing_status
                """
            ).fetchall()
        return {row["stage"]: int(row["n"]) for row in rows}

    # ── 서버(웹) 전용 — 좌표를 브라우저로 노출(ADR-0009 §3). 질의 레이어의 ──
    # ── privacy dataclass(좌표 미포함)를 거치지 않고 dict/Row로 직접 반환한다. ──

    def exposed_gps_points(self) -> list[GpsPoint]:
        """지도용 GPS 점 전량 — 노출 모집단 + 좌표 있는 행을 GpsPoint 리스트로.

        노출 필터(_photo_filter_sql과 동일)·GPS 보유를 강제한다. taken_at은
        전량 KST aware ISO라(M1) ``substr(taken_at,1,10)``이 KST 달력일이다
        — 변환 없이 날짜 그룹 키로 쓴다. 실측 ~5,587점.

        Returns:
            GpsPoint 리스트.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.latitude, p.longitude, substr(p.taken_at, 1, 10) AS date
                FROM photos p
                WHERE p.duplicate_of IS NULL
                  AND p.indexing_status != 'skipped_video'
                  AND p.latitude IS NOT NULL
                  AND p.longitude IS NOT NULL
                """
            ).fetchall()
        return [
            GpsPoint(
                photo_id=r["id"], latitude=r["latitude"], longitude=r["longitude"], date=r["date"]
            )
            for r in rows
        ]

    def exposed_photos_by_date(self, date: str, limit: int = 500) -> list[dict]:
        """특정 KST 달력일의 노출 사진 — 좌표·장소 포함 dict, taken_at 오름차순.

        GPS 없는 사진도 포함한다(latitude NULL 허용) — 그날 위치 미상 사진까지
        날짜 상세 그리드에 나오게. ``substr(taken_at,1,10) = ?``로 KST 달력일을
        매칭한다(M1로 taken_at 전량 KST aware).

        Args:
            date: ``YYYY-MM-DD`` KST 달력일.
            limit: 최대 반환 수 (실측 일 최대 155장 — 기본 500으로 충분).

        Returns:
            id·taken_at·latitude·longitude·country·city dict 리스트.
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.taken_at, p.latitude, p.longitude, p.country, p.city
                FROM photos p
                WHERE p.duplicate_of IS NULL
                  AND p.indexing_status != 'skipped_video'
                  AND substr(p.taken_at, 1, 10) = ?
                ORDER BY p.taken_at, p.id
                LIMIT ?
                """,
                (date, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def no_location_day_groups(self) -> list[dict]:
        """위치 미상 사진의 KST 일별 그룹 — 수동 지오코딩 드로어 입력 (S4, prd §6-b).

        노출 모집단(duplicate·영상 제외) 중 ``latitude IS NULL AND taken_at IS
        NOT NULL``이 대상이다 — 날짜도 없는 사진은 v1 범위 밖(D26-⑥).
        taken_at은 전량 KST aware ISO(M1)라 ``substr(taken_at,1,10)``이 KST
        달력일이다. 실측 2,867장/525일 그룹.

        Returns:
            가치순(trip·장수 우선, 동률 date DESC) dict 리스트 — ``date``·``count``·
            ``sample_photo_ids``(taken_at순 ≤4)·``trip_name``(그룹 내 최빈 trip의
            이름, 없으면 None).
        """
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT p.id, substr(p.taken_at, 1, 10) AS date, t.name AS trip_name
                FROM photos p
                LEFT JOIN trips t ON t.id = p.trip_id
                WHERE p.duplicate_of IS NULL
                  AND p.indexing_status != 'skipped_video'
                  AND p.latitude IS NULL
                  AND p.taken_at IS NOT NULL
                ORDER BY date DESC, p.taken_at, p.id
                """
            ).fetchall()
        grouped: dict[str, dict] = {}  # date DESC 삽입순서 → sorted() stable sort로 동률 date 보존.
        for row in rows:
            group = grouped.setdefault(row["date"], {"count": 0, "samples": [], "trips": Counter()})
            group["count"] += 1
            if len(group["samples"]) < 4:
                group["samples"].append(row["id"])
            if row["trip_name"]:
                group["trips"][row["trip_name"]] += 1
        groups = [
            {
                "date": date,
                "count": group["count"],
                "sample_photo_ids": group["samples"],
                "trip_name": group["trips"].most_common(1)[0][0] if group["trips"] else None,
            }
            for date, group in grouped.items()
        ]
        return sorted(groups, key=lambda g: (g["trip_name"] is None, -g["count"]))

    def update_photo_location(self, photo_ids: list[str], latitude: float, longitude: float) -> int:
        """사진들의 좌표를 일괄 지정하고 location_source='manual'을 마킹한다 (ADR-0009 §4).

        원본 파일은 비파괴(EXIF 미수정) — DB 좌표만 갱신한다. 행정구역 채움은
        기존 reverse 경로(geocode 모듈)가 별도로 수행한다.

        Args:
            photo_ids: 대상 사진 id 목록.
            latitude: 지정 위도.
            longitude: 지정 경도.

        Returns:
            실제 갱신된 행 수 — 미존재 id는 조용히 건너뛴다.
        """
        if not photo_ids:
            return 0
        placeholders = ",".join("?" * len(photo_ids))
        with self.connect() as conn:
            conn.execute(
                f"""
                UPDATE photos SET
                    latitude = ?, longitude = ?, location_source = 'manual',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id IN ({placeholders})
                """,
                (latitude, longitude, *photo_ids),
            )
            return int(conn.execute("SELECT changes()").fetchone()[0])


def _place_match_sql(
    countries: tuple[str, ...], cities: tuple[str, ...]
) -> tuple[list[str], list[object]]:
    """지명 매칭 OR 조각을 만든다 — 필터와 trip 도출이 동일 의미론을 공유한다.

    countries는 country 부분 일치, cities는 city·district 양쪽 부분 일치다
    (기존 매칭 의미론 보존 — 결합만 호출 측에서 OR로 한다).
    """
    ors: list[str] = []
    params: list[object] = []
    for country in countries:
        ors.append("p.country LIKE '%' || ? || '%'")
        params.append(country)
    for city in cities:
        ors.append("(p.city LIKE '%' || ? || '%' OR p.district LIKE '%' || ? || '%')")
        params.extend([city, city])
    return ors, params


def _photo_filter_sql(filters: PhotoQueryFilters) -> tuple[list[str], list[object]]:
    """PhotoQueryFilters를 WHERE 절 조각과 바인딩 파라미터로 변환한다.

    dedup·영상 제외는 필터와 무관하게 항상 포함된다(질의 레이어 불변 규칙).
    날짜 비교는 datetime() 정규화로 소스별 taken_at 포맷 혼재(aware/naive)를
    흡수하며, taken_at 없는 사진은 날짜 필터 시 자연 제외된다.
    장소 조건(countries·cities·trip_ids)은 단일 OR 그룹이다(ADR-0009) —
    "이탈리아" 질의에 geocode 사진(country 매칭)과 GPS 무 trip 사진
    (trip_id 매칭)이 함께 잡힌다. 셋 다 비면 절을 생략한다.
    """
    clauses = ["p.duplicate_of IS NULL", "p.indexing_status != 'skipped_video'"]
    params: list[object] = []
    if filters.date_from:
        clauses.append("datetime(p.taken_at) >= datetime(?)")
        params.append(filters.date_from)
    if filters.date_to:
        clauses.append("datetime(p.taken_at) <= datetime(?)")
        params.append(filters.date_to)
    place_ors, place_params = _place_match_sql(filters.countries, filters.cities)
    if filters.trip_ids:
        placeholders = ",".join("?" * len(filters.trip_ids))
        place_ors.append(f"p.trip_id IN ({placeholders})")
        place_params.extend(filters.trip_ids)
    if place_ors:
        clauses.append(f"({' OR '.join(place_ors)})")
        params.extend(place_params)
    if filters.caption_match:
        clauses.append(
            "EXISTS (SELECT 1 FROM captions c WHERE c.photo_id = p.id"
            " AND c.text LIKE '%' || ? || '%')"
        )
        params.append(filters.caption_match)
    if filters.trip_id:
        clauses.append("p.trip_id = ?")
        params.append(filters.trip_id)
    return clauses, params


def _row_to_trip(row: sqlite3.Row) -> TripRecord:
    return TripRecord(
        id=row["id"],
        name=row["name"],
        start_at=row["start_at"],
        end_at=row["end_at"],
        photo_count=row["photo_count"],
        center_lat=row["center_lat"],
        center_lng=row["center_lng"],
    )


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
        country=row["country"],
        city=row["city"],
        district=row["district"],
        trip_id=row["trip_id"],
        duplicate_of=row["duplicate_of"],
    )

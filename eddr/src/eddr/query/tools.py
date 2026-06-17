"""내부 검색 서비스 — structured 질의 경로, freeform SQL 없음 (ADR-0009).

구 LLM tool surface(ADR-0003, superseded)의 구현 자산을 검색 서비스로 계승한다.
정밀 좌표(latitude/longitude)는 "내 서버 → 내 브라우저" 노출이 허용돼(ADR-0009
§3) 응답 dataclass에 포함하되, 파일 경로·PII EXIF 필드는 여전히 스키마 자체에
없다(ADR-0001 불변 조항). 모든 list 응답은 limit이 강제되어 과대 응답을 차단한다.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Protocol

from eddr.db.repository import EddrDatabase, PhotoQueryFilters, PhotoRecord
from eddr.query.captions import parse_caption
from eddr.types import Embedding

# limit/k 상한 — LLM이 큰 값을 넘겨도 context overflow가 일어나지 않게 클램프.
MAX_LIMIT = 50
# semantic over-fetch 배수 — dedup·필터로 걸러질 후보를 감안해 넉넉히 가져온다.
_OVERFETCH_FACTOR = 5
# qwen3-embedding 권장 질의 instruction(영어) — 문서(캡션) 측은 무지시, 질의 측만 붙인다.
# 미적용 시 retrieval 1~5% 손실(모델 카드). 2026-06-11 벤치: diag@500 0.645→0.733.
QUERY_EMBED_INSTRUCTION = (
    "Instruct: Given a web search query, retrieve relevant passages that answer the query"
    "\nQuery:{query}"
)
# Reciprocal Rank Fusion 상수 — 표준값 60 (Cormack et al. 2009).
_RRF_K = 60
# lexical(BM25) leg 후보 풀 상한.
_LEXICAL_POOL = 1000
# reranker에 넘기는 필터 통과 후보 수 — k보다 깊게 보고 상위 k를 고른다.
_RERANK_POOL = 100


class QueryEmbeddingClient(Protocol):
    """질의 텍스트를 임베딩 벡터로 변환하는 클라이언트 프로토콜."""

    def embed_texts(self, texts: list[str]) -> list[Embedding]:
        """텍스트 목록을 같은 순서의 임베딩 목록으로 변환한다."""
        ...


class VectorSearchStore(Protocol):
    """임베딩으로 가까운 문서를 조회하는 벡터 스토어 프로토콜."""

    def query(self, embedding: Embedding, k: int, where=None):
        """임베딩과 가까운 순서로 최대 k개의 VectorHit을 돌려준다."""
        ...


class NoteVectorStore(Protocol):
    """메모 임베딩 벡터 스토어 프로토콜 (D26 M5, prd §6-d).

    count로 빈 컬렉션을 감지해 note leg를 생략한다 — 메모 0건이면 오버헤드 0.
    """

    def query(self, embedding: Embedding, k: int, where=None):
        """임베딩과 가까운 순서로 최대 k개의 메모 VectorHit을 돌려준다."""
        ...

    def count(self) -> int:
        """컬렉션에 저장된 메모 벡터 수를 돌려준다."""
        ...


class CaptionReranker(Protocol):
    """질의-캡션 쌍을 채점하는 cross-encoder 프로토콜 — 점수가 높을수록 관련."""

    def score(self, query: str, captions: list[str]) -> list[float]:
        """질의와 각 캡션의 관련도 점수를 캡션 순서대로 돌려준다."""
        ...


@dataclass(frozen=True)
class PhotoSummary:
    """사진 목록 응답 한 건 — search_photos·semantic_search_photos 공용.

    Attributes:
        photo_id: 사진 식별자 — get_photo로 상세 조회 가능.
        taken_at: 촬영 시각.
        country: 한국어 국가명 (geocode). 없으면 None.
        city: 한국어 시/도명.
        district: 한국어 구/동명.
        latitude: GPS 위도 — 로컬(브라우저) 노출 허용 (ADR-0009 §3).
        longitude: GPS 경도 — 동일.
        has_location: GPS·geocode 보유 여부 — False면 장소 추정 불가
            (장소 질의 응답 구획용 — 사용자 제안 2026-06-10).
        caption: 캡션 서술 본문 (영어, D19).
        keywords: 캡션 검색 키워드 (bold/plain 머리말 모두 파싱).
        trip_id: 배정된 trip. 없으면 None.
        rank: semantic 검색 순위 (1부터). 메타 검색에선 None.
        distance: 벡터 거리 — 참고용. 절대값을 관련도 컷오프로 쓰지 말 것
            (노트북 05 §D-4 실측: 음성 쿼리 거리가 양성보다 작을 수 있음).
    """

    photo_id: str
    taken_at: str | None
    country: str | None
    city: str | None
    district: str | None
    latitude: float | None
    longitude: float | None
    has_location: bool
    caption: str | None
    keywords: tuple[str, ...]
    trip_id: str | None
    rank: int | None = None
    distance: float | None = None


@dataclass(frozen=True)
class TripSummary:
    """trip 목록 응답 한 건 — list_trips용.

    Attributes:
        trip_id: trip 식별자 — get_trip으로 상세 조회 가능.
        name: 자동 생성 이름 (예: ``이탈리아 여행 2018-04``).
        start_at: 시작 시각 (naive UTC).
        end_at: 끝 시각.
        photo_count: 노출 기준 사진 수 (duplicate 제외).
        country_codes: 방문 국가 ISO 3166-1 alpha-2 — 거주국 제외.
    """

    trip_id: str
    name: str
    start_at: str
    end_at: str
    photo_count: int
    country_codes: tuple[str, ...]


@dataclass(frozen=True)
class TripDetail:
    """trip 상세 응답 — get_trip용.

    Attributes:
        trip_id: trip 식별자.
        name: 자동 생성 이름.
        start_at: 시작 시각.
        end_at: 끝 시각.
        photo_count: 노출 기준 사진 수.
        country_codes: 방문 국가 ISO 코드.
        top_cities: 최빈 방문 도시 (한국어, 최대 5).
        sample_photos: 시간순 대표 사진 (최대 5).
    """

    trip_id: str
    name: str
    start_at: str
    end_at: str
    photo_count: int
    country_codes: tuple[str, ...]
    top_cities: tuple[str, ...]
    sample_photos: tuple[PhotoSummary, ...]


@dataclass(frozen=True)
class PhotoDetail:
    """사진 단건 상세 응답 — get_photo용.

    카메라 제조사·모델은 ADR-0001 전송 가능 목록에 포함된 기본 EXIF다
    (serial 등 PII EXIF는 필드 없음). 좌표는 로컬 노출 허용 필드다
    (ADR-0009 §3 — 지도·라이트박스용).
    """

    photo_id: str
    taken_at: str | None
    country: str | None
    city: str | None
    district: str | None
    latitude: float | None
    longitude: float | None
    has_location: bool
    caption: str | None
    keywords: tuple[str, ...]
    trip_id: str | None
    trip_name: str | None
    width: int | None
    height: int | None
    camera_make: str | None
    camera_model: str | None


class QueryService:
    """내부 검색 서비스 — 서버 라우트가 호출하는 데이터 접근 창구 (ADR-0009).

    Attributes:
        db: EDDR SQLite 저장소.
        vector_store: 캡션 임베딩 벡터 스토어 (semantic 검색용).
        embedding_client: 질의 임베딩 클라이언트 (semantic 검색용).
        note_store: 메모 임베딩 벡터 스토어 (note leg, D26 M5).
    """

    def __init__(
        self,
        db: EddrDatabase,
        vector_store: VectorSearchStore | None = None,
        embedding_client: QueryEmbeddingClient | None = None,
        query_embed_template: str | None = QUERY_EMBED_INSTRUCTION,
        reranker: CaptionReranker | None = None,
        note_store: NoteVectorStore | None = None,
    ):
        """검색 서비스를 조립한다.

        Args:
            db: 초기화된 EddrDatabase.
            vector_store: 벡터 스토어. None이면 semantic_search_photos가 에러 안내를 반환.
            embedding_client: 임베딩 클라이언트. 위와 동일.
            query_embed_template: 질의 임베딩 instruction 템플릿(``{query}`` 치환).
                기본은 qwen3-embedding 권장 형식. None이면 질의를 그대로 임베딩한다.
            reranker: 필터 통과 후보를 재정렬할 cross-encoder. 기본 None(비활성) —
                실험 주입용(scripts/bench_retrieval.py --rerank).
            note_store: 메모 임베딩 컬렉션(eddr_note_text_v1) 핸들. None이거나 비어
                있으면 note leg를 생략한다 — 기존 호출처 호환 (D26 M5).
        """
        self.db = db
        self.vector_store = vector_store
        self.embedding_client = embedding_client
        self.query_embed_template = query_embed_template
        self.reranker = reranker
        self.note_store = note_store

    def search_photos(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        countries: list[str] | None = None,
        cities: list[str] | None = None,
        caption_match: str | None = None,
        trip_id: str | None = None,
        trip_ids: list[str] | None = None,
        limit: int = 20,
    ) -> list[PhotoSummary]:
        """메타데이터 필터로 사진을 검색한다 — 지명·날짜 질의에 적합.

        Args:
            date_from: 촬영 시각 하한 (``YYYY-MM-DD`` 또는 datetime 문자열).
            date_to: 촬영 시각 상한. 날짜만 주면 그날 끝까지 포함.
            countries: 한국어 국가명 부분 일치 (OR).
            cities: 한국어 장소명 부분 일치 — 시/도·구/동 양쪽 매칭 (OR).
            caption_match: 영어 캡션 부분 일치.
            trip_id: trip 정확 일치 — 독립(AND) 조건.
            trip_ids: 장소 스코프 trip 목록 — countries·cities와 OR 결합
                (지명 → trip 도출 경로, prd §6-c).
            limit: 최대 반환 수 (1~50 클램프).

        Returns:
            PhotoSummary 리스트 — geocode 있는 사진이 앞에 온다.
        """
        filters = PhotoQueryFilters(
            date_from=_kst_bound(date_from),
            date_to=_kst_bound(date_to, end=True),
            countries=tuple(countries or ()),
            cities=tuple(cities or ()),
            trip_ids=tuple(trip_ids or ()),
            caption_match=caption_match,
            trip_id=trip_id,
        )
        photos = self.db.query_photos(filters, limit=_clamp(limit))
        captions = self.db.get_latest_captions_for_ids([photo.id for photo in photos])
        return [self._photo_summary(photo, captions.get(photo.id)) for photo in photos]

    def semantic_search_photos(
        self,
        query: str,
        k: int = 20,
        date_from: str | None = None,
        date_to: str | None = None,
        countries: list[str] | None = None,
        cities: list[str] | None = None,
        trip_id: str | None = None,
        trip_ids: list[str] | None = None,
        keywords: list[str] | None = None,
    ) -> list[PhotoSummary]:
        """캡션 임베딩 의미 검색 — 이벤트·객체·음식 등 "무엇" 질의에 적합.

        Chroma 메타데이터에는 geocode·날짜가 없으므로 over-fetch한 뒤
        SQL 측에서 필터(+dedup)를 적용하고 상위 k건을 자른다. 필터 통과분이
        k 미만이면 풀을 ×5씩 확대 재질의한다(스토어 소진 시 중단) — 고정 k×5
        절단이 필터 질의에서 후보 고갈을 일으킴(2026-06-11 retrieval 벤치,
        G02 130장 중 3장 반환).

        Args:
            query: 자연어 질의 (한국어 가능 — multilingual 임베딩).
            k: 최대 반환 수 (1~50 클램프).
            date_from: 촬영 시각 하한.
            date_to: 촬영 시각 상한.
            countries: 한국어 국가명 부분 일치 (OR).
            cities: 한국어 장소명 부분 일치 (OR).
            trip_id: trip 정확 일치 — 독립(AND) 조건.
            trip_ids: 장소 스코프 trip 목록 — countries·cities와 OR 결합
                (지명 → trip 도출 경로, prd §6-c).
            keywords: 캡션에 정확히 나와야 하는 영어 단어/구 (OR). 지정 시
                BM25 lexical 순위를 RRF로 융합한다.

        note_store가 있고 비어 있지 않으면 같은 질의 임베딩으로 메모 컬렉션을
        조회해 note leg를 RRF에 합류시킨다 — 메모 매칭 사진이 결과에 합류한다
        (S5, prd §6-c). 빈 컬렉션이면 leg 생략(기존 순위 비파괴).

        Returns:
            융합 순위(rank) 오름차순 PhotoSummary 리스트. distance는 vector
            leg에서 온 후보만 갖는다(lexical·note 단독 후보는 None).

        Raises:
            RuntimeError: 벡터 스토어/임베딩 클라이언트 미구성 시.
        """
        if self.vector_store is None or self.embedding_client is None:
            raise RuntimeError("semantic search unavailable: vector store not configured")
        k = _clamp(k)
        embed_text = (
            self.query_embed_template.format(query=query) if self.query_embed_template else query
        )
        embedding = self.embedding_client.embed_texts([embed_text])[0]
        filters = PhotoQueryFilters(
            date_from=_kst_bound(date_from),
            date_to=_kst_bound(date_to, end=True),
            countries=tuple(countries or ()),
            cities=tuple(cities or ()),
            trip_ids=tuple(trip_ids or ()),
            trip_id=trip_id,
        )
        lexical_ids: list[str] = []
        if keywords:
            match = " OR ".join(
                f'"{term}"' for term in (kw.replace('"', " ").strip() for kw in keywords) if term
            )
            if match:
                raw_lexical = self.db.search_caption_photo_ids(match, limit=_LEXICAL_POOL)
                # lexical 후보도 동일 필터로 스코프 — 필터 밖 전역 매칭이 융합
                # 순위에 노이즈를 주입하는 회귀를 차단한다(2026-06-11 벤치).
                lexical_ids = self.db.filter_photo_ids(raw_lexical, filters)
        # note leg(D26 M5) — 빈 컬렉션이면 조회 자체를 생략한다(오버헤드 0).
        note_count = self.note_store.count() if self.note_store is not None else 0
        pool_k = k * _OVERFETCH_FACTOR
        while True:
            hits = self.vector_store.query(embedding=embedding, k=pool_k)
            distance_by_id: dict[str, float | None] = {}
            vector_ids: list[str] = []
            vector_distances: list[float] = []
            for hit in hits:
                if hit.photo_id and hit.photo_id not in distance_by_id:
                    vector_ids.append(hit.photo_id)
                    distance_by_id[hit.photo_id] = hit.distance
                    if hit.distance is not None:
                        vector_distances.append(hit.distance)
            note_ids: list[str] = []
            if note_count:
                # 같은 질의 임베딩 사용 — k는 컬렉션 크기로 클램프(과요청 경고 방지).
                note_hits = self.note_store.query(embedding=embedding, k=min(pool_k, note_count))
                vector_ids, note_ids = _fold_note_hits(vector_ids, vector_distances, note_hits)
            candidate_ids = _rrf_fuse(vector_ids, lexical_ids, note_ids)
            passed_all = self.db.filter_photo_ids(candidate_ids, filters)
            passed_ids = passed_all[:k]
            if len(passed_ids) >= k or len(hits) < pool_k:
                break
            pool_k *= _OVERFETCH_FACTOR
        if self.reranker is not None and len(passed_all) > k:
            passed_ids = self._rerank(query, passed_all[:_RERANK_POOL], k)
        captions = self.db.get_latest_captions_for_ids(passed_ids)
        results: list[PhotoSummary] = []
        for rank, photo_id in enumerate(passed_ids, start=1):
            photo = self.db.get_photo(photo_id)
            if photo is None:
                continue
            results.append(
                self._photo_summary(
                    photo,
                    captions.get(photo_id),
                    rank=rank,
                    distance=distance_by_id.get(photo_id),
                )
            )
        return results

    def list_trips(
        self,
        countries: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
    ) -> list[TripSummary]:
        """여행(trip) 목록을 조회한다 — "언제 갔더라" 질의의 1차 진입점.

        Args:
            countries: 한국어 국가명 부분 일치 (trip 이름·소속 사진 국가 매칭).
            date_from: 이 시각 이후에 끝난 trip만.
            date_to: 이 시각 이전에 시작한 trip만.
            limit: 최대 반환 수 (1~50 클램프).

        Returns:
            최신 시작순 TripSummary 리스트.
        """
        trips = self.db.query_trips(
            countries=tuple(countries or ()),
            date_from=_kst_bound(date_from),
            date_to=_kst_bound(date_to, end=True),
            limit=_clamp(limit),
        )
        return [
            TripSummary(
                trip_id=trip.id,
                name=trip.name,
                start_at=trip.start_at,
                end_at=trip.end_at,
                photo_count=trip.photo_count,
                country_codes=tuple(self.db.trip_country_codes(trip.id)),
            )
            for trip in trips
        ]

    def get_trip(self, trip_id: str) -> TripDetail | None:
        """trip 상세를 조회한다 — 방문 도시·대표 사진 포함.

        Args:
            trip_id: 조회할 trip 식별자.

        Returns:
            TripDetail. 없으면 None.
        """
        trip = self.db.get_trip_record(trip_id)
        if trip is None:
            return None
        samples = self.db.query_photos(PhotoQueryFilters(trip_id=trip_id), limit=5)
        sample_caps = self.db.get_latest_captions_for_ids([photo.id for photo in samples])
        return TripDetail(
            trip_id=trip.id,
            name=trip.name,
            start_at=trip.start_at,
            end_at=trip.end_at,
            photo_count=trip.photo_count,
            country_codes=tuple(self.db.trip_country_codes(trip.id)),
            top_cities=tuple(self.db.trip_top_cities(trip.id)),
            sample_photos=tuple(
                self._photo_summary(photo, sample_caps.get(photo.id)) for photo in samples
            ),
        )

    def get_photo(self, photo_id: str) -> PhotoDetail | None:
        """사진 단건 상세를 조회한다. duplicate 마킹 행은 canonical로 따라간다.

        Args:
            photo_id: 조회할 사진 식별자.

        Returns:
            PhotoDetail. 없으면 None.
        """
        photo = self.db.get_photo(photo_id)
        if photo is not None and photo.duplicate_of:
            photo = self.db.get_photo(photo.duplicate_of)
        if photo is None:
            return None
        caption = self.db.get_latest_caption(photo.id)
        parsed = parse_caption(caption) if caption else None
        trip = self.db.get_trip_record(photo.trip_id) if photo.trip_id else None
        return PhotoDetail(
            photo_id=photo.id,
            taken_at=photo.taken_at,
            country=photo.country,
            city=photo.city,
            district=photo.district,
            latitude=photo.latitude,
            longitude=photo.longitude,
            has_location=photo.latitude is not None and photo.longitude is not None,
            caption=parsed.body if parsed else None,
            keywords=parsed.keywords if parsed else (),
            trip_id=photo.trip_id,
            trip_name=trip.name if trip else None,
            width=photo.width,
            height=photo.height,
            camera_make=photo.camera_make,
            camera_model=photo.camera_model,
        )

    def image_path(self, photo_id: str) -> str | None:
        """UI 렌더용 로컬 이미지 경로를 반환한다 — LLM 응답 스키마에는 미포함.

        duplicate 마킹 행은 canonical의 경로를 따른다.
        """
        photo = self.db.get_photo(photo_id)
        if photo is not None and photo.duplicate_of:
            photo = self.db.get_photo(photo.duplicate_of)
        return photo.image_path if photo else None

    def _rerank(self, query: str, photo_ids: list[str], k: int) -> list[str]:
        """cross-encoder 점수로 후보를 재정렬해 상위 k를 반환한다.

        캡션 없는 후보는 채점 불가 — 원래 순서를 유지한 채 뒤에 붙인다.
        """
        caption_by_id = self.db.get_latest_captions_for_ids(photo_ids)
        captioned = [(pid, caption_by_id.get(pid)) for pid in photo_ids]
        scorable = [(pid, caption) for pid, caption in captioned if caption]
        if not scorable:
            return photo_ids[:k]
        scores = self.reranker.score(query, [caption for _, caption in scorable])
        order = sorted(range(len(scorable)), key=lambda i: (-scores[i], scorable[i][0]))
        reranked = [scorable[i][0] for i in order]
        tail = [pid for pid, caption in captioned if not caption]
        return (reranked + tail)[:k]

    def _photo_summary(
        self,
        photo: PhotoRecord,
        caption: str | None,
        rank: int | None = None,
        distance: float | None = None,
    ) -> PhotoSummary:
        parsed = parse_caption(caption) if caption else None
        return PhotoSummary(
            photo_id=photo.id,
            taken_at=photo.taken_at,
            country=photo.country,
            city=photo.city,
            district=photo.district,
            latitude=photo.latitude,
            longitude=photo.longitude,
            has_location=photo.latitude is not None and photo.longitude is not None,
            caption=parsed.body if parsed else None,
            keywords=parsed.keywords if parsed else (),
            trip_id=photo.trip_id,
            rank=rank,
            distance=distance,
        )


def _fold_note_hits(
    vector_ids: list[str],
    vector_distances: list[float],
    note_hits,
) -> tuple[list[str], list[str]]:
    """메모 후보를 캡션 거리 경쟁(가상 순위)으로 vector leg에 병합하고 note leg를 만든다.

    1-item leg의 rank 압축 보정(2026-06-12 실측): 메모 leg rank 1을 그대로 RRF에
    넣으면 1/(K+1) 단독 점수가 vector+lexical 이중 출현 후보들에 밀려 k 절단
    밖으로 떨어진다("개심사 벚꽃"에서 전 캡션보다 가까운 메모가 64위). 캡션과
    메모는 같은 임베딩 공간이므로 거리로 직접 경쟁시킨다:

    - 캡션 풀 거리 분포에 메모 거리를 삽입(가상 순위)해 풀 안에 들면 채택 —
      vector leg(병합)와 note leg 양쪽에 출현해 이중 합의 후보로 경쟁한다.
    - 풀 경쟁에서 탈락한 메모(전 후보보다 먼 거리)는 기여 0 — 무관 질의를
      오염시키지 않는다. 절대 거리 컷오프는 쓰지 않는다(노트북 05 §D-4).

    Args:
        vector_ids: 캡션 leg photo_id (거리 오름차순, dedup 완료).
        vector_distances: 위와 같은 순서의 거리 목록.
        note_hits: 메모 컬렉션 VectorHit 목록 (거리 오름차순).

    Returns:
        (병합된 vector leg, note leg) — note leg는 채택된 메모 사진의 거리순.
    """
    folded = list(vector_ids)
    distances = list(vector_distances)  # folded와 정렬 정합 유지 — 채택 시 함께 삽입
    # 입장(탈락) 판정은 원본 캡션 풀 기준, 순위 삽입은 갱신 풀 기준으로 분리한다 —
    # 캡션이 있으면 두 기준이 동치(채택 메모 거리 ≤ 원본 최대)고, 캡션 풀이 비면
    # 경쟁 상대가 없으므로 전원 채택된다 (M5 리뷰 이슈 3).
    pool_max = vector_distances[-1] if vector_distances else None
    note_ids: list[str] = []
    for hit in note_hits:
        if not hit.photo_id or hit.distance is None or hit.photo_id in note_ids:
            continue
        if pool_max is not None and hit.distance > pool_max:
            continue  # 풀 경쟁 탈락 — 전 캡션 후보보다 먼 메모
        note_ids.append(hit.photo_id)
        virtual_rank = bisect.bisect_left(distances, hit.distance)
        if hit.photo_id in folded:
            idx = folded.index(hit.photo_id)
            if virtual_rank >= idx:
                continue  # 자기 캡션이 이미 더 가까움 — min 유지, 강등 금지 (이슈 1)
            del folded[idx]
            del distances[idx]
        folded.insert(virtual_rank, hit.photo_id)
        # 채택 거리를 경쟁 풀에 반영 — 후속 메모의 과승격·동률 사전순 결정 방지 (이슈 2).
        distances.insert(virtual_rank, hit.distance)
    return folded, note_ids


def _rrf_fuse(*ranked_lists: list[str]) -> list[str]:
    """ranked 리스트들을 Reciprocal Rank Fusion(1/(K+rank) 합산)으로 융합한다.

    가변 인자 — vector·lexical·note leg를 받는다 (D26 M5). 빈 리스트는 기여가
    없어 leg 생략과 동치고, 단일 리스트면 원 순서가 보존된다(점수가 순위
    단조감소). 동점은 photo_id 사전순 — 결과를 결정적으로 유지한다.
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, photo_id in enumerate(ranked, start=1):
            scores[photo_id] = scores.get(photo_id, 0.0) + 1.0 / (_RRF_K + rank)
    return sorted(scores, key=lambda photo_id: (-scores[photo_id], photo_id))


def _clamp(limit: int) -> int:
    """limit/k를 1~MAX_LIMIT 범위로 강제한다 (ADR-0003 context overflow 차단)."""
    return max(1, min(int(limit), MAX_LIMIT))


def _kst_bound(value: str | None, *, end: bool = False) -> str | None:
    """날짜 경계를 KST(+09:00) aware로 정규화한다 — "하루" = KST 달력일 (ADR-0009 §6).

    taken_at이 전량 KST aware ISO라 SQLite ``datetime()`` 비교는 UTC 타임라인에서
    일어난다 — naive 경계를 그대로 바인딩하면 UTC로 오해석되어 필터 윈도가
    +9시간 밀린다(M3 품질 리뷰 C1). bare 날짜는 그날 시작/끝의 KST aware로,
    naive datetime은 +09:00 부여로 보정한다. trips(naive UTC 저장) 비교도
    ``datetime()``의 UTC 변환을 거치므로 같은 경계값으로 정합하다.

    Args:
        value: ``YYYY-MM-DD`` 또는 datetime 문자열(naive/aware). None이면 그대로.
        end: True면 bare 날짜를 그날 끝(23:59:59)으로 보정한다(상한용).

    Returns:
        KST aware 경계 문자열 (입력이 이미 aware면 원문 유지).
    """
    if not value:
        return value
    if len(value) == 10:
        return f"{value}T23:59:59+09:00" if end else f"{value}T00:00:00+09:00"
    has_tz = value.endswith("Z") or "+" in value[10:] or "-" in value[11:]
    return value if has_tz else f"{value}+09:00"

"""QueryService 5 tools 검증 — privacy 스키마·dedup·GPS 분리·rank·limit 강제."""

from dataclasses import asdict, fields
from pathlib import Path

import pytest

from eddr.db.repository import EddrDatabase, PhotoRecord
from eddr.query.tools import (
    MAX_LIMIT,
    QUERY_EMBED_INSTRUCTION,
    PhotoDetail,
    PhotoSummary,
    QueryService,
    _fold_note_hits,
    _rrf_fuse,
)
from eddr.vector.chroma_store import VectorHit


def make_db(tmp_path: Path) -> EddrDatabase:
    """trip 1개·국내외 사진·duplicate·영상·GPS 무 사진을 가진 테스트 DB."""
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()

    def add(photo_id: str, **kwargs) -> None:
        defaults = {
            "source": "photos_library",
            "source_uri": photo_id,
            "image_path": f"/photos/{photo_id}.jpg",
            "indexing_status": "caption_done",
        }
        db.upsert_photo(PhotoRecord(id=photo_id, **{**defaults, **kwargs}))

    add("p1", taken_at="2018-04-01 10:00:00", latitude=41.9, longitude=12.5)
    add("p2", taken_at="2018-04-02 11:00:00", latitude=43.7, longitude=11.2)
    add("p3", taken_at="2018-04-03 12:00:00")  # GPS 없음 — trip 기간 내
    add(
        "p4",
        taken_at="2020-01-05 09:00:00",
        latitude=37.5,
        longitude=126.9,
        width=4032,
        height=3024,
        camera_make="Apple",
        camera_model="iPhone 12",
    )
    add("p5", taken_at="2021-07-01 08:00:00", source="local")
    db.update_photo_geo("p1", "이탈리아", "로마", None)
    db.update_photo_geo("p2", "이탈리아", "피렌체", None)
    db.update_photo_geo("p4", "대한민국", "서울특별시", "마포구")
    db.upsert_caption(
        "p4",
        "gemma4:e2b",
        "en",
        "A wedding cake on a table.\n\n**Search keywords:** wedding, cake, celebration",
    )
    db.upsert_caption(
        "p1",
        "gemma4:e2b",
        "en",
        "A stone plaza with ancient ruins.\n\nSearch keywords: ruins, plaza, travel",
    )
    with db.connect() as conn:
        conn.execute("UPDATE photos SET duplicate_of = 'p4' WHERE id = 'p5'")

    db.insert_trip(
        "trip_20180401_01",
        "이탈리아 여행 2018-04",
        "2018-04-01 00:00:00",
        "2018-04-04 00:00:00",
        42.0,
        12.0,
    )
    db.insert_trip_countries("trip_20180401_01", ["IT"])
    db.assign_trip_by_timerange("trip_20180401_01", "2018-04-01 00:00:00", "2018-04-04 00:00:00")
    db.finalize_trip_photo_counts()
    return db


class FakeEmbeddingClient:
    def __init__(self):
        self.texts = []

    def embed_texts(self, texts):
        self.texts.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorStore:
    """거리순 후보를 고정 반환 — duplicate(p5)·미존재 id 포함해 후처리 필터를 자극한다."""

    def __init__(self, ordered_ids):
        self.ordered_ids = ordered_ids
        self.last_k = None
        self.requested = []

    def query(self, embedding, k, where=None):
        self.last_k = k
        self.requested.append(k)
        return [
            VectorHit(
                id=f"v:{pid}", photo_id=pid, document="", metadata={}, distance=0.5 + 0.01 * i
            )
            for i, pid in enumerate(self.ordered_ids)
        ][:k]


@pytest.fixture()
def service(tmp_path: Path) -> QueryService:
    db = make_db(tmp_path)
    store = FakeVectorStore(["p4", "p5", "missing", "p1", "p3"])
    return QueryService(db, vector_store=store, embedding_client=FakeEmbeddingClient())


def test_response_schemas_expose_coordinates_but_no_paths_or_pii():
    # ADR-0009 §3: 정밀 좌표는 "내 서버 → 내 브라우저" 노출 허용 — 스키마에 포함.
    # ADR-0001 불변 조항: 파일 경로·소스 식별자 등 PII 필드는 여전히 스키마 자체에 없다.
    for schema in (PhotoSummary, PhotoDetail):
        names = {f.name for f in fields(schema)}
        assert {"latitude", "longitude"} <= names
        assert not names & {"image_path", "source_uri"}


def test_date_filters_match_kst_calendar_days(tmp_path: Path):
    """날짜 필터가 KST 달력일과 정확히 일치한다 (ADR-0009 §6, 품질 리뷰 C1 회귀).

    taken_at은 전량 KST aware라 SQLite datetime() 비교가 UTC 타임라인에서
    일어난다 — 경계를 naive로 바인딩하면 +9h 밀려 KST 새벽 사진이 누락되고
    다음 날 사진이 섞인다. _kst_bound가 경계를 aware로 보정해야 한다.
    """
    db = EddrDatabase(tmp_path / "kst.sqlite")
    db.initialize()
    for photo_id, taken_at in [
        ("dawn", "2024-01-10T07:30:00+09:00"),  # UTC로는 전날 22:30 — 시프트 시 누락되던 케이스
        ("night", "2024-01-10T23:50:00+09:00"),
        ("next-morning", "2024-01-11T08:00:00+09:00"),  # UTC로는 10일 23:00 — 시프트 시 오염
    ]:
        db.upsert_photo(
            PhotoRecord(
                id=photo_id,
                source="photos_library",
                source_uri=photo_id,
                image_path=f"/photos/{photo_id}.jpg",
                indexing_status="caption_done",
                taken_at=taken_at,
            )
        )
    service = QueryService(
        db, vector_store=FakeVectorStore([]), embedding_client=FakeEmbeddingClient()
    )

    results = service.search_photos(date_from="2024-01-10", date_to="2024-01-10")

    assert {p.photo_id for p in results} == {"dawn", "night"}


def test_search_photos_filters_and_orders(service: QueryService):
    results = service.search_photos(countries=["이탈리아"])
    assert [p.photo_id for p in results] == ["p2", "p1"]
    assert results[1].caption == "A stone plaza with ancient ruins."
    assert results[1].keywords == ("ruins", "plaza", "travel")

    in_trip = service.search_photos(trip_id="trip_20180401_01")
    assert [p.photo_id for p in in_trip] == ["p1", "p2", "p3"]
    assert in_trip[2].has_location is False  # GPS 무 사진은 하단 + 플래그

    # duplicate(p5)·영상 미노출, limit 클램프
    everything = service.search_photos(limit=999)
    assert "p5" not in [p.photo_id for p in everything]
    assert len(everything) <= MAX_LIMIT


def test_search_photos_date_to_includes_full_day(service: QueryService):
    results = service.search_photos(date_from="2018-04-02", date_to="2018-04-02")
    assert [p.photo_id for p in results] == ["p2"]


def test_photo_summary_carries_coordinates(service: QueryService):
    # 좌표는 lane·지도 렌더 입력 (ADR-0009 §3) — GPS 무 사진은 None.
    results = {p.photo_id: p for p in service.search_photos(trip_id="trip_20180401_01")}
    assert (results["p1"].latitude, results["p1"].longitude) == (41.9, 12.5)
    assert (results["p3"].latitude, results["p3"].longitude) == (None, None)


def test_search_photos_trip_ids_or_extends_place_scope(service: QueryService):
    # countries와 trip_ids는 OR — geocode 무 사진(p3)이 trip 소속으로 함께 잡힌다.
    results = service.search_photos(countries=["이탈리아"], trip_ids=["trip_20180401_01"])
    assert {p.photo_id for p in results} == {"p1", "p2", "p3"}


def test_semantic_search_trip_ids_or_extends_place_scope(service: QueryService):
    # store 순서 p4→p1→p3 중 장소(이탈리아 OR trip) 통과는 p1·p3 — p4(대한민국, trip 무)는 탈락.
    results = service.semantic_search_photos(
        "유적", k=5, countries=["이탈리아"], trip_ids=["trip_20180401_01"]
    )
    assert [p.photo_id for p in results] == ["p1", "p3"]
    assert [p.rank for p in results] == [1, 2]


def test_semantic_search_overfetches_dedups_and_ranks(service: QueryService):
    results = service.semantic_search_photos("결혼식 케이크", k=3)
    # p5(duplicate)·missing 제거, 거리순 유지, rank는 1부터
    assert [p.photo_id for p in results] == ["p4", "p1", "p3"]
    assert [p.rank for p in results] == [1, 2, 3]
    assert results[0].distance is not None
    assert service.vector_store.last_k == 15  # k*5 over-fetch

    filtered = service.semantic_search_photos("유적", k=3, countries=["이탈리아"])
    assert [p.photo_id for p in filtered] == ["p1"]
    assert filtered[0].rank == 1  # 필터 후 재순위


def test_semantic_search_escalates_overfetch_until_k_or_exhausted(tmp_path: Path):
    # 필터 통과분이 1차 풀(k*5) 밖 깊은 순위에 있는 filter starvation 상황 재현.
    db = make_db(tmp_path)
    store = FakeVectorStore(["p4", "p3", "m1", "m2", "m3", "p1", "p2"])
    service = QueryService(db, vector_store=store, embedding_client=FakeEmbeddingClient())

    results = service.semantic_search_photos("유적", k=1, countries=["이탈리아"])
    assert [p.photo_id for p in results] == ["p1"]
    assert store.requested == [5, 25]  # 1차 5건에서 0건 통과 → 풀 확대 후 충족

    store.requested.clear()
    none = service.semantic_search_photos("유적", k=1, countries=["프랑스"])
    assert none == []
    assert store.requested == [5, 25]  # 25 요청에 7건 반환(스토어 소진) → 확대 중단


def test_semantic_search_fuses_keywords_with_rrf(tmp_path: Path):
    db = make_db(tmp_path)
    store = FakeVectorStore(["p4", "p1", "p3"])
    service = QueryService(db, vector_store=store, embedding_client=FakeEmbeddingClient())

    vector_only = service.semantic_search_photos("유적", k=3)
    assert [p.photo_id for p in vector_only] == ["p4", "p1", "p3"]

    # lexical(p1 캡션의 ruins)이 RRF 융합으로 p1을 1위로 끌어올린다
    fused = service.semantic_search_photos("유적", k=3, keywords=["ruins"])
    assert [p.photo_id for p in fused] == ["p1", "p4", "p3"]

    # vector 풀에 없는 lexical 단독 후보(p2)도 융합 결과에 들어오고 distance는 없다
    db.upsert_caption("p2", "gemma4:e2b", "en", "A mountain lake at dawn.")
    mixed = service.semantic_search_photos("유적", k=4, keywords=["mountain"])
    p2 = next(p for p in mixed if p.photo_id == "p2")
    assert p2.distance is None
    assert p2.rank is not None


class FakeNoteStore(FakeVectorStore):
    """메모 컬렉션 대역 — count()·거리 경쟁(가상 순위) 경로를 검증한다 (D26 M5).

    base_distance 기본 0.5는 FakeVectorStore 캡션 거리와 동일 — 풀 경쟁 통과.
    """

    def __init__(self, ordered_ids, base_distance=0.5):
        super().__init__(ordered_ids)
        self.base_distance = base_distance

    def query(self, embedding, k, where=None):
        self.last_k = k
        self.requested.append(k)
        return [
            VectorHit(
                id=f"n:{pid}",
                photo_id=pid,
                document="",
                metadata={},
                distance=self.base_distance + 0.01 * i,
            )
            for i, pid in enumerate(self.ordered_ids)
        ][:k]

    def count(self):
        return len(self.ordered_ids)


def test_rrf_fuse_is_variadic_and_deterministic():
    # 단일 리스트 — 원 순서 보존(점수가 순위 단조감소).
    assert _rrf_fuse(["a", "b", "c"]) == ["a", "b", "c"]
    # 빈 leg는 기여 0 — leg 생략과 동치.
    assert _rrf_fuse(["a", "b"], [], []) == ["a", "b"]
    # 3-leg 융합 — 두 leg에 겹친 b가 1위, 동점(a·d)은 photo_id 사전순.
    assert _rrf_fuse(["a", "b"], ["b", "c"], ["d"]) == ["b", "a", "d", "c"]


def test_fold_note_hits_multi_memo_precision():
    """다건 메모 정밀도 (M5 리뷰 이슈 1·2) — min 승격 유지·채택 거리의 풀 갱신."""

    def note(pid: str, distance: float) -> VectorHit:
        return VectorHit(id=f"n:{pid}", photo_id=pid, document="", metadata={}, distance=distance)

    # 자기 캡션(0.1)이 메모(0.25)보다 가까운 c1은 강등되지 않는다(이슈 1).
    folded, note_ids = _fold_note_hits(
        ["c1", "c2", "c3"], [0.1, 0.2, 0.3], [note("m1", 0.15), note("c1", 0.25)]
    )
    assert folded == ["c1", "m1", "c2", "c3"]
    assert note_ids == ["m1", "c1"]

    # 앞선 채택(m1=0.15)이 거리 풀에 반영돼 m2(0.25)가 c2(0.2)를 추월하지 않는다(이슈 2).
    folded, note_ids = _fold_note_hits(
        ["c1", "c2", "c3"], [0.1, 0.2, 0.3], [note("m1", 0.15), note("m2", 0.25)]
    )
    assert folded == ["c1", "m1", "c2", "m2", "c3"]
    assert note_ids == ["m1", "m2"]

    # 캡션 풀이 비면 경쟁 상대가 없다 — 메모 거리순 그대로 채택(이슈 3).
    folded, note_ids = _fold_note_hits([], [], [note("m1", 0.4), note("m2", 0.7)])
    assert folded == ["m1", "m2"]
    assert note_ids == ["m1", "m2"]


def test_semantic_search_note_leg_joins_and_respects_exposure(tmp_path: Path):
    db = make_db(tmp_path)
    client = FakeEmbeddingClient()
    notes = FakeNoteStore(["p3", "p5"])  # p3=메모 매칭, p5=duplicate(노출 제외)
    service = QueryService(
        db, vector_store=FakeVectorStore(["p4", "p1"]), embedding_client=client, note_store=notes
    )

    results = service.semantic_search_photos("벚꽃 나들이", k=4)

    ids = [p.photo_id for p in results]
    # 거리 동률 메모는 병합 vector leg + note leg 이중 출현 — 최상위로 합류 (S5).
    assert ids[0] == "p3"
    assert "p5" not in ids  # note leg 후보도 노출 필터(duplicate 제외)를 통과해야 한다
    note_only = next(p for p in results if p.photo_id == "p3")
    assert note_only.distance is None  # 캡션 vector leg 밖 후보 — distance 없음
    assert note_only.rank is not None
    assert len(client.texts) == 1  # 질의 임베딩 1회 — 캡션·메모 leg가 공유
    assert notes.requested == [2]  # 조회 k는 컬렉션 크기(2)로 클램프


def test_semantic_search_far_note_does_not_pollute_unrelated_query(tmp_path: Path):
    db = make_db(tmp_path)
    # 메모 거리(9.9)가 캡션 풀 전 후보보다 멀다 — 거리 경쟁 탈락, 기여 0.
    notes = FakeNoteStore(["p3"], base_distance=9.9)
    service = QueryService(
        db,
        vector_store=FakeVectorStore(["p4", "p1"]),
        embedding_client=FakeEmbeddingClient(),
        note_store=notes,
    )

    results = service.semantic_search_photos("은하수", k=3)

    assert [p.photo_id for p in results] == ["p4", "p1"]  # 무관 질의 비오염


def test_semantic_search_skips_note_leg_when_collection_empty(tmp_path: Path):
    db = make_db(tmp_path)
    notes = FakeNoteStore([])
    service = QueryService(
        db,
        vector_store=FakeVectorStore(["p4", "p1", "p3"]),
        embedding_client=FakeEmbeddingClient(),
        note_store=notes,
    )

    results = service.semantic_search_photos("유적", k=3)

    # 기존 순위 비파괴 — 빈 컬렉션이면 leg 생략, 조회 0회(오버헤드 0).
    assert [p.photo_id for p in results] == ["p4", "p1", "p3"]
    assert notes.requested == []


class FakeReranker:
    def __init__(self):
        self.calls = []

    def score(self, query, captions):
        self.calls.append((query, list(captions)))
        return [2.0 if "ruins" in caption else 0.5 for caption in captions]


def test_semantic_search_reranks_candidates_when_reranker_injected(tmp_path: Path):
    db = make_db(tmp_path)
    store = FakeVectorStore(["p4", "p1", "p3"])
    reranker = FakeReranker()
    service = QueryService(
        db,
        vector_store=store,
        embedding_client=FakeEmbeddingClient(),
        reranker=reranker,
    )
    results = service.semantic_search_photos("유적", k=2)
    # vector 1위는 p4지만 reranker가 ruins 캡션(p1)을 1위로 — 캡션 없는 p3는 후순위
    assert [p.photo_id for p in results] == ["p1", "p4"]
    assert reranker.calls and reranker.calls[0][0] == "유적"


def test_semantic_search_applies_query_instruction_by_default(tmp_path: Path):
    # 질의 측에만 instruction을 붙인다 — 문서(캡션) 인덱싱 경로는 raw 유지.
    db = make_db(tmp_path)
    client = FakeEmbeddingClient()
    service = QueryService(db, vector_store=FakeVectorStore(["p4"]), embedding_client=client)
    service.semantic_search_photos("결혼식", k=1)
    assert client.texts == [QUERY_EMBED_INSTRUCTION.format(query="결혼식")]

    raw_client = FakeEmbeddingClient()
    raw = QueryService(
        db,
        vector_store=FakeVectorStore(["p4"]),
        embedding_client=raw_client,
        query_embed_template=None,
    )
    raw.semantic_search_photos("결혼식", k=1)
    assert raw_client.texts == ["결혼식"]


def test_semantic_search_without_store_raises(tmp_path: Path):
    service = QueryService(make_db(tmp_path))
    with pytest.raises(RuntimeError):
        service.semantic_search_photos("아무거나")


def test_list_trips_and_get_trip(service: QueryService):
    trips = service.list_trips(countries=["이탈리아"])
    assert len(trips) == 1
    assert trips[0].country_codes == ("IT",)
    assert trips[0].photo_count == 3

    detail = service.get_trip("trip_20180401_01")
    assert detail is not None
    assert detail.top_cities == ("로마", "피렌체")
    assert [p.photo_id for p in detail.sample_photos] == ["p1", "p2", "p3"]
    assert service.get_trip("trip_unknown") is None


def test_get_photo_follows_duplicate_to_canonical(service: QueryService):
    detail = service.get_photo("p5")
    assert detail is not None
    assert detail.photo_id == "p4"  # duplicate → canonical
    assert detail.camera_model == "iPhone 12"
    assert detail.trip_name is None
    assert detail.keywords == ("wedding", "cake", "celebration")
    assert service.get_photo("missing") is None

    in_trip = service.get_photo("p1")
    assert in_trip.trip_name == "이탈리아 여행 2018-04"

    # 좌표는 canonical(p4) 행에서 온다 — 로컬 노출 허용 필드 (ADR-0009 §3)
    assert (asdict(detail)["latitude"], asdict(detail)["longitude"]) == (37.5, 126.9)


def test_image_path_is_ui_side_channel(service: QueryService):
    assert service.image_path("p1") == "/photos/p1.jpg"
    assert service.image_path("p5") == "/photos/p4.jpg"  # canonical 경로
    assert service.image_path("missing") is None


def test_search_paths_batch_captions_no_n_plus_1(tmp_path: Path, monkeypatch):
    """검색 경로가 사진별 get_latest_caption(N+1) 대신 배치 조회만 쓴다.

    search_photos·semantic_search_photos 응답 조립에서 단건 캡션 호출이
    0이어야 한다 (N+1 재발 회귀 가드).
    """
    db = make_db(tmp_path)
    single = 0
    batch = 0
    real_single = db.get_latest_caption
    real_batch = db.get_latest_captions_for_ids

    def counting_single(photo_id):
        nonlocal single
        single += 1
        return real_single(photo_id)

    def counting_batch(photo_ids):
        nonlocal batch
        batch += 1
        return real_batch(photo_ids)

    monkeypatch.setattr(db, "get_latest_caption", counting_single)
    monkeypatch.setattr(db, "get_latest_captions_for_ids", counting_batch)

    store = FakeVectorStore(["p4", "p5", "missing", "p1", "p3"])
    service = QueryService(db, vector_store=store, embedding_client=FakeEmbeddingClient())

    service.search_photos()
    service.semantic_search_photos("ruins", k=5)

    assert single == 0  # 단건 N+1 호출 없음
    assert batch >= 1  # 배치 경로 사용

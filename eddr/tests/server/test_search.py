"""검색 라우트 계약 검증 — 그룹핑·관련도 정렬·trip 스코프·503·422 (D26 M3, prd §6-b·§6-c)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eddr.db.repository import PhotoRecord
from eddr.query.extract import ExtractedQuery
from eddr.query.tools import QueryService
from eddr.server.app import create_app
from eddr.server.deps import AppState, ServerConfig
from eddr.server.routes.search import is_date_intent
from tests.query.test_tools import FakeEmbeddingClient, FakeVectorStore, make_db


class FakeExtractor:
    """QueryExtractor 대역 — 고정 추출 결과 또는 예외를 돌려준다."""

    def __init__(self, result: ExtractedQuery | Exception):
        self.result = result
        self.queries: list[str] = []

    def extract(self, query: str) -> ExtractedQuery:
        self.queries.append(query)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _client(tmp_path: Path, ordered_ids: list[str], extractor: FakeExtractor) -> TestClient:
    """make_db에 같은 날짜 사진(p6)·날짜 무 사진(p7)을 얹은 검색 환경."""
    db = make_db(tmp_path)
    db.upsert_photo(
        PhotoRecord(
            id="p6",
            source="photos_library",
            source_uri="p6",
            taken_at="2018-04-01 17:00:00",
            latitude=41.8,
            longitude=12.4,
            indexing_status="caption_done",
        )
    )
    db.update_photo_geo("p6", "이탈리아", "로마", None)
    db.upsert_photo(
        PhotoRecord(id="p7", source="local", source_uri="p7", indexing_status="caption_done")
    )
    service = QueryService(
        db, vector_store=FakeVectorStore(ordered_ids), embedding_client=FakeEmbeddingClient()
    )
    config = ServerConfig(
        root=tmp_path, db_path=tmp_path / "eddr.sqlite", chroma_path=tmp_path / "chroma"
    )
    return TestClient(create_app(AppState(config, service, extractor=extractor)))


def test_is_date_intent_matches_time_interrogatives():
    assert is_date_intent("내가 이탈리아를 언제 갔더라?")
    assert is_date_intent("부산 여행 몇 년에 갔지?")
    assert is_date_intent("몇월에 찍은 거야")
    assert is_date_intent("며칠에 찍었어")


def test_is_date_intent_ignores_photo_list_queries():
    assert not is_date_intent("이탈리아 여행 사진 찾아줘")
    assert not is_date_intent("바다 풍경 보여줘")
    assert not is_date_intent("용산에서 뭘 먹었었는지 보여줘")


def test_search_orders_lanes_by_date_for_date_intent_query(tmp_path: Path):
    extractor = FakeExtractor(ExtractedQuery(keywords_en=()))
    client = _client(tmp_path, ["p4", "p6", "p1", "p2", "p7"], extractor)

    body = client.post("/api/search", json={"query": "이 사진들 언제 찍었더라"}).json()

    # "언제" → 날짜 오름차순(rank 무관, 이른 날 top), date 없는 그룹은 말미.
    assert [g["date"] for g in body["groups"]] == ["2018-04-01", "2018-04-02", "2020-01-05", None]


def test_search_groups_by_kst_date_and_sorts_by_relevance(tmp_path: Path):
    extractor = FakeExtractor(ExtractedQuery(keywords_en=()))
    client = _client(tmp_path, ["p4", "p6", "p1", "p2", "p7"], extractor)

    body = client.post("/api/search", json={"query": "결혼식 케이크"}).json()

    assert extractor.queries == ["결혼식 케이크"]  # 임베딩 질의는 원문 유지
    assert body["total"] == 5
    assert body["interpretation"] == {
        "keywords_en": [],
        "keywords_ko": [],
        "date_from": None,
        "date_to": None,
        "countries": [],
        "cities": [],
        "fallback": False,
    }
    # 그룹 정렬 = 그룹 내 최고 rank(관련도, D26-⑦) — 최신순이 아니다.
    assert [g["date"] for g in body["groups"]] == ["2020-01-05", "2018-04-01", "2018-04-02", None]
    same_day = body["groups"][1]
    assert [p["photo_id"] for p in same_day["photos"]] == ["p6", "p1"]  # 그룹 내도 rank순
    assert [p["rank"] for p in same_day["photos"]] == [2, 3]
    # place = 그룹 최빈 city → country → None.
    assert body["groups"][0]["place"] == "서울특별시"
    assert same_day["place"] == "로마"
    assert body["groups"][3]["place"] is None  # p7 — 날짜·geocode 모두 없음
    photo = same_day["photos"][0]
    assert photo == {
        "photo_id": "p6",
        "taken_at": "2018-04-01 17:00:00",
        "latitude": 41.8,
        "longitude": 12.4,
        "rank": 2,
    }


def test_search_scopes_places_through_trip_ids(tmp_path: Path):
    # "이탈리아" 추출 → trip 도출 → geocode 무 p3가 trip 소속으로 잡히고 p4는 탈락.
    extractor = FakeExtractor(ExtractedQuery(countries=("이탈리아",)))
    client = _client(tmp_path, ["p3", "p4"], extractor)

    body = client.post("/api/search", json={"query": "이탈리아 사진"}).json()

    assert body["total"] == 1
    assert [g["date"] for g in body["groups"]] == ["2018-04-03"]
    assert [p["photo_id"] for p in body["groups"][0]["photos"]] == ["p3"]
    assert body["interpretation"]["countries"] == ["이탈리아"]


def test_search_returns_503_when_ollama_down(tmp_path: Path):
    extractor = FakeExtractor(ConnectionError("Failed to connect to Ollama"))
    client = _client(tmp_path, ["p4"], extractor)

    response = client.post("/api/search", json={"query": "은하수"})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "로컬 모델 서버(ollama)가 꺼져 있어요. ollama serve 후 다시 시도해 주세요."
    )


def test_search_rejects_blank_query(tmp_path: Path):
    extractor = FakeExtractor(ExtractedQuery())
    client = _client(tmp_path, ["p4"], extractor)

    assert client.post("/api/search", json={"query": "   "}).status_code == 422
    assert client.post("/api/search", json={}).status_code == 422
    assert extractor.queries == []  # 빈 질의는 추출기까지 가지 않는다


@pytest.mark.parametrize("fallback", [True, False])
def test_search_interpretation_echoes_fallback_flag(tmp_path: Path, fallback: bool):
    extractor = FakeExtractor(ExtractedQuery(fallback=fallback))
    client = _client(tmp_path, ["p4"], extractor)

    body = client.post("/api/search", json={"query": "아무거나"}).json()

    assert body["interpretation"]["fallback"] is fallback

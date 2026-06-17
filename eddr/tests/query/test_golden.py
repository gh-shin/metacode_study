"""골든셋 v2 러너 테스트 — match 3종 파싱·평가(AND)·보류·리포트 (실 골든셋 비의존)."""

from pathlib import Path

import pytest

from eddr.query.extract import ExtractedQuery
from eddr.query.golden import (
    GoldenQuestion,
    evaluate_match,
    load_golden_set,
    run_golden_set,
    write_report,
)
from eddr.query.tools import PhotoSummary, QueryService
from eddr.server.routes.search import run_search
from tests.query.test_tools import FakeEmbeddingClient, FakeVectorStore, make_db

# 가상 문항 3개 — 3종 match 각 1 (실제 골든 문항과 무관).
GOLDEN_YAML = """\
version: 2
questions:
  - id: T01
    question: "자전거 라이딩 사진"
    match:
      photo_ids_any: ["p1", "p9"]
  - id: T02
    question: "눈사람 만든 날이 언제였지?"
    answer_type: fact
    expect: "2024-01-10 lane 상위"
    reference:
      note: "가상 참고치"
    match:
      date_lane_top: {date: "2024-01-10", within: 2}
  - id: T03
    question: "할로윈 호박 사진"
    match:
      caption_contains_any: {words: ["pumpkin"], top_k: 2}
"""


def _photo(
    photo_id: str,
    taken_at: str | None,
    rank: int,
    caption: str | None = None,
    keywords: tuple[str, ...] = (),
) -> PhotoSummary:
    return PhotoSummary(
        photo_id=photo_id,
        taken_at=taken_at,
        country=None,
        city=None,
        district=None,
        latitude=None,
        longitude=None,
        has_location=False,
        caption=caption,
        keywords=keywords,
        trip_id=None,
        rank=rank,
    )


# rank순 고정 결과 — 2024-01-10 lane(상위) + 2023-05-05 lane.
RESULTS = [
    _photo("p1", "2024-01-10 21:00:00+09:00", 1, "A carved pumpkin on a porch.", ("halloween",)),
    _photo("p2", "2024-01-10 09:00:00+09:00", 2, "A snowman in a park."),
    _photo("p3", "2023-05-05 12:00:00+09:00", 3),
]


def _search_fn(query: str) -> tuple[ExtractedQuery, list[PhotoSummary]]:
    """fake 검색 — 어떤 질의든 고정 추출·고정 결과를 돌려준다."""
    return ExtractedQuery(keywords_en=("bike",)), list(RESULTS)


def test_run_golden_set_orders_lanes_by_date_for_fact_question():
    """date-intent 질의는 lane을 날짜순 정렬 — trip 시작일이 상위에 온다 (G08)."""
    results = [
        _photo("p1", "2024-01-10 10:00:00+09:00", 1),  # 늦은 날짜, 좋은 rank
        _photo("p2", "2023-05-05 10:00:00+09:00", 2),  # 이른 날짜, 나쁜 rank
    ]

    def search_fn(query: str) -> tuple[ExtractedQuery, list[PhotoSummary]]:
        return ExtractedQuery(keywords_en=()), list(results)

    question = GoldenQuestion(
        id="T_DATE",
        question="이 사진들 언제 찍었더라?",  # "언제" → date intent
        match={"date_lane_top": {"date": "2023-05-05", "within": 1}},
    )

    rows = run_golden_set([question], search_fn)

    assert rows[0].verdict == "PASS"


def test_load_golden_set_parses_match_rules(tmp_path: Path):
    path = tmp_path / "golden.yaml"
    path.write_text(GOLDEN_YAML, encoding="utf-8")
    questions = load_golden_set(path)
    assert [q.id for q in questions] == ["T01", "T02", "T03"]
    assert questions[0].match == {"photo_ids_any": ["p1", "p9"]}
    assert questions[1].match == {"date_lane_top": {"date": "2024-01-10", "within": 2}}
    assert questions[1].answer_type == "fact"
    assert questions[1].reference == {"note": "가상 참고치"}
    assert questions[2].match == {"caption_contains_any": {"words": ["pumpkin"], "top_k": 2}}


def test_run_golden_set_passes_all_three_rule_kinds(tmp_path: Path):
    path = tmp_path / "golden.yaml"
    path.write_text(GOLDEN_YAML, encoding="utf-8")
    progress: list[str] = []

    rows = run_golden_set(load_golden_set(path), _search_fn, on_progress=progress.append)

    assert [row.verdict for row in rows] == ["PASS", "PASS", "PASS"]
    assert len(progress) == 3
    # 미리보기 필드 — 추출 결과·lane(관련도순)·상위 사진이 리포트 입력으로 남는다.
    assert rows[0].interpretation.keywords_en == ("bike",)
    assert [lane.date for lane in rows[0].lanes] == ["2024-01-10", "2023-05-05"]
    assert rows[0].top_photos[0].photo_id == "p1"


def test_evaluate_match_fails_each_rule_and_ands_them():
    from eddr.server.routes.search import group_by_kst_date

    groups = group_by_kst_date(RESULTS)
    ok, reasons = evaluate_match({"photo_ids_any": ["p404"]}, RESULTS, groups)
    assert ok is False
    assert "photo_ids_any" in reasons[0]

    ok, _ = evaluate_match({"date_lane_top": {"date": "2023-05-05", "within": 1}}, RESULTS, groups)
    assert ok is False  # 2023-05-05는 2번째 lane — within 1 밖
    ok, _ = evaluate_match({"date_lane_top": {"date": "2023-05-05", "within": 2}}, RESULTS, groups)
    assert ok is True

    # top_k가 캡션 매칭 범위를 자른다 — pumpkin은 rank 1에만 있다.
    ok, _ = evaluate_match(
        {"caption_contains_any": {"words": ["snowman"], "top_k": 1}}, RESULTS, groups
    )
    assert ok is False
    # 키워드도 캡션 본문과 함께 매칭 대상이다.
    ok, _ = evaluate_match(
        {"caption_contains_any": {"words": ["halloween"], "top_k": 1}}, RESULTS, groups
    )
    assert ok is True

    # 복수 규칙 AND — 하나라도 미충족이면 FAIL, 근거는 규칙별로 남는다.
    ok, reasons = evaluate_match(
        {"photo_ids_any": ["p1"], "date_lane_top": {"date": "1999-01-01", "within": 3}},
        RESULTS,
        groups,
    )
    assert ok is False
    assert any("충족 — p1" in reason for reason in reasons)
    assert any("미충족" in reason for reason in reasons)

    # 알 수 없는 규칙 키 = 오타 — 조용한 통과 대신 FAIL.
    ok, reasons = evaluate_match({"photo_ids_all": ["p1"]}, RESULTS, groups)
    assert ok is False
    assert "알 수 없는 match 규칙" in reasons[0]


def test_run_golden_set_holds_questions_without_match():
    questions = [GoldenQuestion(id="T10", question="규칙 없는 문항")]
    rows = run_golden_set(questions, _search_fn)
    assert rows[0].verdict == "보류"
    # 보류여도 검색은 실행 — 사용자가 match를 작성할 미리보기를 남긴다.
    assert rows[0].total == 3
    assert rows[0].interpretation is not None


def test_run_golden_set_records_error_and_continues():
    def flaky(query: str):
        if "터지는" in query:
            raise ValueError("embedding shape mismatch")
        return _search_fn(query)

    questions = [
        GoldenQuestion(id="T11", question="터지는 문항", match={"photo_ids_any": ["p1"]}),
        GoldenQuestion(id="T12", question="정상 문항", match={"photo_ids_any": ["p1"]}),
    ]
    rows = run_golden_set(questions, flaky)
    assert rows[0].verdict == "FAIL"
    assert "실행 오류" in rows[0].reasons[0]
    assert rows[1].verdict == "PASS"


def test_run_golden_set_propagates_connection_error():
    def down(query: str):
        raise ConnectionError("ollama down")

    with pytest.raises(ConnectionError):
        run_golden_set([GoldenQuestion(id="T13", question="q")], down)


def test_run_golden_set_through_search_pipeline(tmp_path: Path):
    """run_search(라우트 코어) 경유 — fake extractor·fake service로 HTTP 비경유 검증."""

    class FakeExtractor:
        def extract(self, query: str) -> ExtractedQuery:
            return ExtractedQuery()

    db = make_db(tmp_path)
    service = QueryService(
        db, vector_store=FakeVectorStore(["p4", "p1"]), embedding_client=FakeEmbeddingClient()
    )
    extractor = FakeExtractor()
    questions = [
        GoldenQuestion(id="T20", question="결혼식 케이크", match={"photo_ids_any": ["p4"]})
    ]

    rows = run_golden_set(questions, lambda query: run_search(extractor, service, query))

    assert rows[0].verdict == "PASS"
    assert rows[0].lanes[0].date == "2020-01-05"  # p4(rank 1)의 KST 달력일


def test_write_report_includes_guide_and_holds_outside_denominator(tmp_path: Path):
    path = tmp_path / "golden.yaml"
    path.write_text(GOLDEN_YAML, encoding="utf-8")
    questions = [*load_golden_set(path), GoldenQuestion(id="T99", question="보류 문항")]
    rows = run_golden_set(questions, _search_fn)

    report = tmp_path / "report.md"
    write_report(rows, report, questions=questions)
    text = report.read_text(encoding="utf-8")

    assert "match 작성 가이드" in text  # 상단 주석 — 3종 문법 안내
    assert "photo_ids_any" in text
    assert "date_lane_top" in text
    assert "caption_contains_any" in text
    assert "PASS 3 / FAIL 0** (채점 분모 3 — 보류 1문항 제외)" in text
    assert "## T99 — 보류 문항" in text
    assert "2024-01-10" in text  # 상위 lane 미리보기
    assert "기대(사람 기준): 2024-01-10 lane 상위" in text

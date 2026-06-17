"""RAG quality report utilities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eddr.eval.rag_quality import (
    ExperimentRecord,
    load_experiment_records,
    load_question_specs,
    render_assignment_report,
    summarize_experiments,
)

QUESTIONS_YAML = """\
version: 2
questions:
  - id: G01
    question: "이탈리아 산악 풍경"
    category: multi_document_semantic
    assignment_type: 여러 문서를 종합해야 하는 질문
    difficulty: medium
    answer_type: photo_list
    expected_signal: "산악 풍경"
    match:
      caption_contains_any:
        words: ["mountain"]
        top_k: 20
  - id: G02
    question: "내가 이탈리아를 언제 갔더라?"
    category: simple_fact
    assignment_type: 단순 사실 조회
    difficulty: easy
    answer_type: fact
    expected_signal: "날짜 lane"
    match:
      date_lane_top:
        date: "2019-06-29"
        within: 3
"""


def _record(label: str, mean: float, latency: float = 4.2, k: int = 20) -> dict:
    return {
        "ts": "2026-06-14 16:00:00",
        "git_rev": "abc1234",
        "label": label,
        "config": {
            "k": k,
            "embed_model": "qwen3-embedding:8b",
            "instruct": (
                None if "raw" in label else "Instruct: Given a web search query\nQuery:{query}"
            ),
            "rrf": "rrf" in label,
            "rerank": False,
        },
        "questions": [
            {
                "qid": "G01",
                "gt_size": 10,
                "returned": 20,
                "hits": 8,
                "recall@k": 0.8,
                "recall_norm": mean,
                "precision": 0.4,
                "latency_s": latency,
                "diag_recall@100": 0.5,
                "diag_recall@500": 0.7,
                "diag_recall@2000": 1.0,
            }
        ],
        "aggregate": {
            "mean_recall@k": mean,
            "mean_recall_norm": mean,
            "mean_diag_recall@500": 0.7,
            "mean_returned": 20.0,
            "total_latency_s": latency,
        },
    }


def test_load_question_specs_keeps_assignment_metadata(tmp_path: Path):
    path = tmp_path / "questions.yaml"
    path.write_text(QUESTIONS_YAML, encoding="utf-8")

    questions = load_question_specs(path)

    assert [q.id for q in questions] == ["G01", "G02"]
    assert questions[0].assignment_type == "여러 문서를 종합해야 하는 질문"
    assert questions[1].difficulty == "easy"
    assert questions[1].match["date_lane_top"]["date"] == "2019-06-29"


def test_load_question_specs_rejects_missing_required_fields(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text("version: 2\nquestions:\n  - id: G01\n", encoding="utf-8")

    with pytest.raises(ValueError, match="question"):
        load_question_specs(path)


def test_load_experiment_records_reads_jsonl(tmp_path: Path):
    path = tmp_path / "experiments.jsonl"
    path.write_text(
        json.dumps(_record("baseline-raw-k20", 0.5), ensure_ascii=False)
        + "\n"
        + json.dumps(_record("exp1-instruct-default-k20", 0.9), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    records = load_experiment_records(path)

    assert [r.label for r in records] == ["baseline-raw-k20", "exp1-instruct-default-k20"]
    assert records[1].mean_recall_norm == 0.9
    assert records[0].config["k"] == 20


def test_summarize_experiments_computes_delta_against_baseline():
    records = [
        ExperimentRecord.from_json(_record("baseline-raw-k20", 0.5)),
        ExperimentRecord.from_json(_record("exp1-instruct-default-k20", 0.65)),
        ExperimentRecord.from_json(_record("exp2-topk50", 0.75, latency=8.0)),
    ]

    rows = summarize_experiments(records, baseline_label="baseline-raw-k20")

    assert rows[0]["delta"] == 0.0
    assert rows[1]["delta"] == 0.15
    assert rows[2]["total_latency_s"] == 8.0


def test_render_assignment_report_contains_required_sections(tmp_path: Path):
    qpath = tmp_path / "questions.yaml"
    qpath.write_text(QUESTIONS_YAML, encoding="utf-8")
    questions = load_question_specs(qpath)
    records = [
        ExperimentRecord.from_json(_record("baseline-raw-k20", 0.5)),
        ExperimentRecord.from_json(_record("exp1-instruct-default-k20", 0.65)),
    ]

    report = render_assignment_report(
        questions=questions,
        records=records,
        baseline_label="baseline-raw-k20",
        golden_report_path=Path("reports/rag_quality/golden/example.md"),
    )

    assert "# EDDR RAG 품질 평가 및 개선 리포트" in report
    assert "## 1. 평가용 질문셋" in report
    assert "## 2. Baseline RAG 설정" in report
    assert "## 3. 성능 개선 실험" in report
    assert "## 4. 결과 분석" in report
    assert "baseline-raw-k20" in report
    assert "exp1-instruct-default-k20" in report
    assert "retrieval microbench는" in report
    assert "G04/G08" in report


def test_render_assignment_report_summarizes_golden_report_failures(tmp_path: Path):
    qpath = tmp_path / "questions.yaml"
    qpath.write_text(QUESTIONS_YAML, encoding="utf-8")
    golden_path = tmp_path / "golden.md"
    golden_path.write_text(
        """\
# 골든셋 v2 자동 채점 리포트

- **PASS 9 / FAIL 1** (채점 분모 10 — 보류 0문항 제외)

## G08 — 내가 이탈리아를 언제 갔더라?

- 판정: **FAIL**
  - date_lane_top: 미충족 — 2019-06-29 ∉ 상위 3 lane ['2019-07-11', '2019-06-30', '2019-07-07']
""",
        encoding="utf-8",
    )
    questions = load_question_specs(qpath)
    records = [
        ExperimentRecord.from_json(_record("baseline-raw-k20", 0.5)),
        ExperimentRecord.from_json(_record("exp1-instruct-default-k20", 0.65)),
    ]

    report = render_assignment_report(
        questions=questions,
        records=records,
        baseline_label="baseline-raw-k20",
        golden_report_path=golden_path,
    )

    assert "PASS 9 / FAIL 1 / 보류 0" in report
    assert "G08" in report
    assert "date_lane_top: 미충족" in report
    assert "2019-06-29 ∉ 상위 3 lane" in report


def test_render_assignment_report_marks_g06_as_weak_pass_when_golden_report_shows_it(
    tmp_path: Path,
):
    qpath = tmp_path / "questions.yaml"
    qpath.write_text(QUESTIONS_YAML, encoding="utf-8")
    golden_path = tmp_path / "golden.md"
    golden_path.write_text(
        """\
# 골든셋 v2 자동 채점 리포트

- **PASS 2 / FAIL 0** (채점 분모 2 — 보류 0문항 제외)

## G06 — 개심사에서 절 건물과 꽃이 함께 나온 사진 찾아줘

- 판정: **PASS**
  - photo_ids_any: 충족 — local:example 포함
""",
        encoding="utf-8",
    )
    questions = load_question_specs(qpath)
    records = [
        ExperimentRecord.from_json(_record("baseline-raw-k20", 0.5)),
        ExperimentRecord.from_json(_record("exp1-instruct-default-k20", 0.65)),
    ]

    report = render_assignment_report(
        questions=questions,
        records=records,
        baseline_label="baseline-raw-k20",
        golden_report_path=golden_path,
    )

    assert "G06 caveat" in report
    assert "약한 통과" in report


def test_render_assignment_report_preserves_non_mismatch_golden_failures(tmp_path: Path):
    qpath = tmp_path / "questions.yaml"
    qpath.write_text(QUESTIONS_YAML, encoding="utf-8")
    golden_path = tmp_path / "golden.md"
    golden_path.write_text(
        """\
# 골든셋 v2 자동 채점 리포트

- **PASS 1 / FAIL 1** (채점 분모 2 — 보류 0문항 제외)

## G02 — 아이슬란드 여행에서 차량 이동이나 도로가 나온 사진을 찾아줘

- 판정: **FAIL**
  - 실행 오류: RuntimeError: extractor timeout
""",
        encoding="utf-8",
    )
    questions = load_question_specs(qpath)
    records = [
        ExperimentRecord.from_json(_record("baseline-raw-k20", 0.5)),
        ExperimentRecord.from_json(_record("exp1-instruct-default-k20", 0.65)),
    ]

    report = render_assignment_report(
        questions=questions,
        records=records,
        baseline_label="baseline-raw-k20",
        golden_report_path=golden_path,
    )

    assert "G02: 실행 오류: RuntimeError: extractor timeout" in report


def test_render_assignment_report_conclusion_uses_named_baseline_when_records_are_reordered(
    tmp_path: Path,
):
    qpath = tmp_path / "questions.yaml"
    qpath.write_text(QUESTIONS_YAML, encoding="utf-8")
    questions = load_question_specs(qpath)
    records = [
        ExperimentRecord.from_json(_record("exp1-instruct-default-k20", 0.65)),
        ExperimentRecord.from_json(_record("baseline-raw-k20", 0.5)),
    ]

    report = render_assignment_report(
        questions=questions,
        records=records,
        baseline_label="baseline-raw-k20",
    )

    conclusion = report.split("## 1. 평가용 질문셋", maxsplit=1)[0]
    assert "기준선 `baseline-raw-k20`" in conclusion
    assert "기준선 `exp1-instruct-default-k20`" not in conclusion


def test_render_assignment_report_conclusion_distinguishes_larger_k_from_same_k(
    tmp_path: Path,
):
    qpath = tmp_path / "questions.yaml"
    qpath.write_text(QUESTIONS_YAML, encoding="utf-8")
    questions = load_question_specs(qpath)
    records = [
        ExperimentRecord.from_json(_record("baseline-raw-k20", 0.551, k=20)),
        ExperimentRecord.from_json(_record("exp1-instruct-default-k20", 0.726, k=20)),
        ExperimentRecord.from_json(_record("exp2-topk50", 0.735, k=50)),
    ]

    report = render_assignment_report(
        questions=questions,
        records=records,
        baseline_label="baseline-raw-k20",
    )

    conclusion = report.split("## 1. 평가용 질문셋", maxsplit=1)[0]
    assert "`exp2-topk50`" in conclusion
    assert "탐색 폭" in conclusion
    assert "동일 k=20 비교" in conclusion
    assert "`exp1-instruct-default-k20`" in conclusion

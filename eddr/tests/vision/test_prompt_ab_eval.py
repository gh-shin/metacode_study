import json
from pathlib import Path

from eddr.query.audit import CaptionAuditLabel
from eddr.vision.prompt_ab_eval import (
    DEFAULT_FORBIDDEN_KEYWORDS,
    evaluate_prompt_ab_outputs,
)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_evaluate_prompt_ab_outputs_scores_forbidden_terms_and_positive_recall(tmp_path: Path):
    out = tmp_path / "prompt_ab.jsonl"
    write_jsonl(
        out,
        [
            {
                "photo_id": "sprouts",
                "caption_model": "gemma4:e2b",
                "captions": {
                    "p3_hybrid_food_guard": (
                        "Caption: A bowl of bean sprouts.\n\n"
                        "Search keywords: bean sprouts, broth, light noodles"
                    )
                },
                "leaks": {"p3_hybrid_food_guard": []},
                "errors": {},
            },
            {
                "photo_id": "cold-noodles",
                "caption_model": "gemma4:e2b",
                "captions": {
                    "p3_hybrid_food_guard": (
                        "Caption: A bowl of cold noodles.\n\n"
                        "Search keywords: cold noodles, broth, egg"
                    )
                },
                "leaks": {"p3_hybrid_food_guard": []},
                "errors": {},
            },
        ],
    )
    labels = {
        "sprouts": CaptionAuditLabel(
            visual_target=False,
            caption_claims_target=True,
            review_label="wrong_object_sprouts_as_noodles",
        ),
        "cold-noodles": CaptionAuditLabel(
            visual_target=True,
            caption_claims_target=False,
            review_label="exact_dish_missing",
        ),
    }

    report = evaluate_prompt_ab_outputs(
        paths=[out],
        labels=labels,
        forbidden_keywords=("noodles", "ramen", "pasta", "naengmyeon"),
        positive_keywords=("cold noodles", "noodles", "naengmyeon"),
    )

    summary = report.summaries[("gemma4:e2b", "p3_hybrid_food_guard")]
    assert summary.rows == 2
    assert summary.format_ok == 2
    assert summary.privacy_ok == 2
    assert summary.false_forbidden_keyword_hits == 1
    assert summary.positive_keyword_hits == 1

    sprouts = next(row for row in report.rows if row.photo_id == "sprouts")
    assert sprouts.keyword_count == 3
    assert sprouts.forbidden_keyword_hits == ("noodles",)
    assert sprouts.positive_keyword_hit is False


def test_evaluate_prompt_ab_outputs_keeps_unlabeled_rows_for_format_and_privacy(tmp_path: Path):
    out = tmp_path / "prompt_ab.jsonl"
    write_jsonl(
        out,
        [
            {
                "photo_id": "unlabeled",
                "caption_model": "qwen3-vl:8b",
                "captions": {"p3_hybrid": "Caption only without keyword section."},
                "leaks": {"p3_hybrid": ["image_path"]},
                "errors": {},
            }
        ],
    )

    report = evaluate_prompt_ab_outputs(paths=[out], labels={})

    summary = report.summaries[("qwen3-vl:8b", "p3_hybrid")]
    assert summary.rows == 1
    assert summary.format_ok == 0
    assert summary.privacy_ok == 0
    assert summary.false_forbidden_keyword_hits == 0
    assert summary.positive_keyword_hits == 0


def test_evaluate_prompt_ab_outputs_counts_failed_prompts_against_gates(tmp_path: Path):
    out = tmp_path / "prompt_ab.jsonl"
    write_jsonl(
        out,
        [
            {
                "photo_id": "sprouts",
                "caption_model": "qwen3-vl:8b",
                "captions": {},
                "leaks": {"p3_hybrid_food_guard": []},
                "errors": {
                    "p3_hybrid_food_guard": "caption contains sensitive metadata: image_path"
                },
            }
        ],
    )

    report = evaluate_prompt_ab_outputs(
        paths=[out],
        labels={
            "sprouts": CaptionAuditLabel(
                visual_target=False,
                caption_claims_target=True,
                review_label="wrong_object_sprouts_as_noodles",
            )
        },
    )

    summary = report.summaries[("qwen3-vl:8b", "p3_hybrid_food_guard")]
    assert summary.rows == 1
    assert summary.format_ok == 0
    assert summary.privacy_ok == 0
    assert summary.format_pass is False
    assert summary.privacy_pass is False
    assert summary.passes_gates is False
    assert report.rows[0].error == "caption contains sensitive metadata: image_path"


def test_evaluate_prompt_ab_outputs_reports_gate_denominators_and_passes(tmp_path: Path):
    out = tmp_path / "prompt_ab.jsonl"
    write_jsonl(
        out,
        [
            {
                "photo_id": "sprouts",
                "caption_model": "qwen3-vl:8b",
                "captions": {
                    "p3_hybrid_food_guard": (
                        "Caption: Bean sprouts.\n\n"
                        "Search keywords: bean sprouts, soup, rice, green onions"
                    )
                },
                "leaks": {"p3_hybrid_food_guard": []},
                "errors": {},
            },
            {
                "photo_id": "cold-noodles",
                "caption_model": "qwen3-vl:8b",
                "captions": {
                    "p3_hybrid_food_guard": (
                        "Caption: Cold noodles.\n\n"
                        "Search keywords: cold noodle, broth, egg, Korean food"
                    )
                },
                "leaks": {"p3_hybrid_food_guard": []},
                "errors": {},
            },
        ],
    )
    labels = {
        "sprouts": CaptionAuditLabel(False, True, "wrong_object_sprouts_as_noodles"),
        "cold-noodles": CaptionAuditLabel(True, False, "exact_dish_missing"),
    }

    report = evaluate_prompt_ab_outputs(paths=[out], labels=labels, keyword_min=4, keyword_max=6)

    summary = report.summaries[("qwen3-vl:8b", "p3_hybrid_food_guard")]
    assert summary.negative_rows == 1
    assert summary.positive_rows == 1
    assert summary.false_forbidden_keyword_hits == 0
    assert summary.positive_keyword_hits == 1
    assert summary.positive_recall == 1.0
    assert summary.false_forbidden_pass is True
    assert summary.positive_recall_pass is True
    assert summary.format_pass is True
    assert summary.privacy_pass is True
    assert summary.passes_gates is True


def test_default_forbidden_keywords_cover_singular_noodle_and_vermicelli():
    assert "noodle" in DEFAULT_FORBIDDEN_KEYWORDS
    assert "vermicelli" in DEFAULT_FORBIDDEN_KEYWORDS

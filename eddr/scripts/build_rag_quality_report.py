"""Build the EDDR RAG quality assignment report from benchmark artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from eddr.eval.rag_quality import (
    load_experiment_records,
    load_question_specs,
    render_assignment_report,
)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Build RAG quality assignment report")
    parser.add_argument("--questions", type=Path, default=Path("docs/rag_quality/questions.yaml"))
    parser.add_argument(
        "--experiments",
        type=Path,
        default=Path("reports/rag_quality/retrieval/experiments.jsonl"),
    )
    parser.add_argument("--baseline-label", default="baseline-raw-k20")
    parser.add_argument("--golden-report", type=Path, default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("reports/rag_quality/ASSIGNMENT_REPORT.md"),
    )
    args = parser.parse_args()

    questions = load_question_specs(args.questions)
    records = load_experiment_records(args.experiments)
    report = render_assignment_report(
        questions=questions,
        records=records,
        baseline_label=args.baseline_label,
        golden_report_path=args.golden_report,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

"""Controlled RAG experiment runner and report helpers."""

from __future__ import annotations

import argparse
import json
import math
import platform
import re
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


RUNS: dict[str, dict[str, Any]] = {
    "R0_baseline": {
        "label": "BL",
        "variant": "baseline",
        "executable": True,
        "changed": "baseline QueryService: dense caption vector + FTS5 BM25 + note legs",
    },
    "R1_dense_multiquery": {
        "label": "MQ",
        "variant": "multiquery",
        "executable": True,
        "changed": "dense vector leg receives generated alternative queries",
    },
    "R2_image_leg": {
        "label": "IMG",
        "variant": None,
        "executable": False,
        "changed": "image vector leg",
        "blocked_by": "no image embedding retrieval leg or image-vector collection is implemented",
    },
    "R3_neural_sparse": {
        "label": "NSP",
        "variant": None,
        "executable": False,
        "changed": "neural sparse vector leg",
        "blocked_by": "only SQLite FTS5 BM25 sparse lexical retrieval exists; no SPLADE/BGE-M3 sparse index",
    },
    "R4_late_interaction": {
        "label": "LI",
        "variant": None,
        "executable": False,
        "changed": "late interaction rerank",
        "blocked_by": "no ColBERT-style late-interaction index/reranker exists; cross-encoder is a different variant",
    },
}

_PHOTO_ID_RE = re.compile(r"(?:photos_library|google_takeout|local):[0-9A-Fa-f-]+")
_QUESTION_ID_RE = re.compile(r"Q\d{3}")
_NEGATIVE_FOOD_LABELS = {
    "wrong_object_sprouts_or_sides_as_noodles": "negative_sprout_as_noodle",
    "shredded_garnish_or_thin_strands_boundary": "negative_sprout_as_noodle",
    "text_menu_product_false_positive": "negative_text_menu_product",
    "duplicate_amplification": "negative_duplicate",
}
_POSITIVE_FOOD_LABELS = {
    "positive_control_real_noodle_recall": "positive_real_noodle",
    "positive_control_sprout_recall": "positive_sprout",
}


@dataclass(frozen=True)
class CandidateSpec:
    id: str
    source_file: str
    query: str
    answer_type: str
    eval_role: str
    source_hint: str
    expected_photo_ids: tuple[str, ...]
    gt_status: str
    visual: bool
    food_label: str
    fp_gate_role: str
    bucket: str


def load_candidate_specs(
    candidate_path: Path,
    food_path: Path,
    golden_path: Path | None = Path("docs/golden_set.yaml"),
) -> list[CandidateSpec]:
    """Normalize existing candidate markdown into the PRD schema."""
    anchors = _load_golden_anchor_ids(golden_path) if golden_path and golden_path.exists() else {}
    return [
        *_load_question_candidates(candidate_path, anchors),
        *_load_food_candidates(food_path),
    ]


def count_food_false_positives(photo_ids: list[str], specs: list[CandidateSpec]) -> int:
    negative_ids = {
        photo_id
        for spec in specs
        if spec.food_label.startswith("negative_")
        for photo_id in spec.expected_photo_ids
    }
    return sum(1 for photo_id in photo_ids if photo_id in negative_ids)


def render_final_report(*, batch_id: str, run_summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# RAG Controlled Experiments Final Technical Report",
        "",
        f"Batch: `{batch_id}`",
        "",
        "## 결론 요약",
        "",
        _recommendation(run_summaries),
        "",
        "## 실행 가능 Matrix",
        "",
        "| run_id | executable | variant | changed | reason |",
        "|---|---:|---|---|---|",
    ]
    for run_id, run in RUNS.items():
        lines.append(
            f"| {run_id} | {'O' if run['executable'] else 'X'} | "
            f"{run.get('variant') or '-'} | {run['changed']} | {run.get('blocked_by', '-')} |"
        )
    lines += [
        "",
        "## 결과 요약",
        "",
        "| run_id | status | macro recall@20 | food FP@20 | p95 latency | 의견 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for summary in run_summaries:
        lines.append(
            f"| {summary['run_id']} | {summary['status']} | "
            f"{_fmt(summary.get('macro_recall_at_20'))} | "
            f"{summary.get('food_false_positive_count_top20', '-')} | "
            f"{_fmt(summary.get('p95_latency_ms'))}ms | {summary.get('comment', '')} |"
        )
    lines += [
        "",
        "## 최종 권고",
        "",
        _recommendation(run_summaries),
    ]
    return "\n".join(lines) + "\n"


def render_variant_delta(run_summaries: list[dict[str, Any]]) -> str:
    baseline = next((row for row in run_summaries if row["run_id"] == "R0_baseline"), None)
    baseline_recall = baseline.get("macro_recall_at_20") if baseline else None
    baseline_latency = baseline.get("p95_latency_ms") if baseline else None
    lines = [
        "# RAG Controlled Experiments Variant Delta",
        "",
        "| Run | Status | Macro recall@20 | Delta vs R0 | Food FP@20 | p95 latency | Latency ratio | Decision |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in run_summaries:
        recall = row.get("macro_recall_at_20")
        latency = row.get("p95_latency_ms")
        delta = (
            round(recall - baseline_recall, 3)
            if recall is not None and baseline_recall is not None
            else None
        )
        ratio = (
            round(latency / baseline_latency, 1)
            if latency is not None and baseline_latency
            else None
        )
        lines.append(
            f"| {row['run_id']} | {row['status']} | {_fmt(recall)} | {_fmt(delta)} | "
            f"{row.get('food_false_positive_count_top20', '-')} | {_fmt(latency)}ms | "
            f"{_fmt_ratio(ratio)} | {_decision(row, ratio)} |"
        )
    return "\n".join(lines) + "\n"


def run_batch(args: argparse.Namespace) -> list[dict[str, Any]]:
    output = args.out
    output.mkdir(parents=True, exist_ok=True)
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    specs = load_candidate_specs(args.candidates, args.food_candidates)
    _write_yaml(output / "candidate_normalized.yaml", {"questions": [asdict(spec) for spec in specs]})
    _write_json(
        output / "batch_manifest.json",
        {
            "batch_id": batch_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "git_rev": _git_rev(),
            "db": str(args.db),
            "chroma": str(args.chroma),
            "candidate_count": len(specs),
            "runs": RUNS,
        },
    )

    selected_runs = [item.strip() for item in args.runs.split(",") if item.strip()]
    question_specs = [spec for spec in specs if spec.id.startswith("Q")]
    food_specs = [spec for spec in specs if spec.id.startswith("F")]
    run_summaries: list[dict[str, Any]] = []

    executable = [run_id for run_id in selected_runs if RUNS[run_id]["executable"]]
    freeze = _build_extractor_freeze(question_specs, args.ollama_host) if executable else {}
    if freeze:
        _write_json(output / "baseline_freeze.json", freeze)

    for run_id in selected_runs:
        run_dir = output / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        run = RUNS[run_id]
        if not run["executable"]:
            summary = _write_blocked_run(run_dir, run_id, run, question_specs, food_specs, args)
        else:
            summary = _run_executable(
                run_dir, run_id, run, question_specs, food_specs, specs, freeze, args
            )
        run_summaries.append(summary)

    final_report = render_final_report(batch_id=batch_id, run_summaries=run_summaries)
    (output / "final_technical_report.md").write_text(final_report, encoding="utf-8")
    (output / "variant_delta.md").write_text(render_variant_delta(run_summaries), encoding="utf-8")
    return run_summaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run RAG controlled experiments")
    parser.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    parser.add_argument("--chroma", type=Path, default=Path("data/index/chroma"))
    parser.add_argument("--out", type=Path, default=Path("reports/rag_experiments"))
    parser.add_argument("--candidates", type=Path, default=Path("docs/GOLDEN_QUERY_CANDIDATES.md"))
    parser.add_argument(
        "--food-candidates",
        type=Path,
        default=Path("reports/caption_audit/20260613_food_strand_candidate_set.md"),
    )
    parser.add_argument("--ollama-host", default=None)
    parser.add_argument("--k", type=int, default=50)
    parser.add_argument("--runs", default=",".join(RUNS))
    args = parser.parse_args(argv)
    unknown = [run_id for run_id in args.runs.split(",") if run_id and run_id not in RUNS]
    if unknown:
        parser.error(f"unknown run ids: {', '.join(unknown)}")
    run_batch(args)
    print(f"wrote {args.out}")
    return 0


def _load_question_candidates(path: Path, anchors: dict[str, tuple[str, ...]]) -> list[CandidateSpec]:
    specs: list[CandidateSpec] = []
    header: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and cells[0] == "ID":
            header = cells
            continue
        if not cells or not _QUESTION_ID_RE.fullmatch(cells[0]):
            continue
        if len(header) == 5:
            source_hint, why, query, answer_type = cells[1], cells[2], cells[3], cells[4]
            bucket = "priority"
        else:
            source_hint, why, query, answer_type = cells[2], cells[4], cells[3], cells[5]
            bucket = cells[1].strip("`")
        answer = answer_type.replace("`", "")
        role = "primary" if answer == "photo_id list" else "diagnostic"
        expected = tuple(_PHOTO_ID_RE.findall(line)) or anchors.get(cells[0], ())
        specs.append(
            CandidateSpec(
                id=cells[0],
                source_file=str(path),
                query=query,
                answer_type=answer,
                eval_role=role,
                source_hint=f"{source_hint} / {why}",
                expected_photo_ids=expected,
                gt_status="confirmed" if expected and role == "primary" else "missing",
                visual=role == "primary",
                food_label="none",
                fp_gate_role="food_probe" if ("음식" in query or "카페" in query) else "none",
                bucket=bucket,
            )
        )
    return specs


def _load_food_candidates(path: Path) -> list[CandidateSpec]:
    specs: list[CandidateSpec] = []
    heading = ""
    index = 1
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            heading = line[4:].strip()
            continue
        if line.startswith("## "):
            heading = line[3:].strip()
            continue
        photo_ids = _PHOTO_ID_RE.findall(line)
        if not photo_ids:
            continue
        for photo_id in photo_ids:
            label = _NEGATIVE_FOOD_LABELS.get(heading) or _POSITIVE_FOOD_LABELS.get(heading)
            if label is None and "true noodle" in line:
                label = "positive_real_noodle"
            elif label is None and "sprout" in line and "control" in line:
                label = "positive_sprout"
            elif label is None:
                label = "none"
            specs.append(
                CandidateSpec(
                    id=f"F{index:03d}",
                    source_file=str(path),
                    query="",
                    answer_type="food bucket",
                    eval_role="diagnostic",
                    source_hint=line.strip("- "),
                    expected_photo_ids=(photo_id,),
                    gt_status="proxy",
                    visual=label.startswith("positive_"),
                    food_label=label,
                    fp_gate_role=(
                        "negative_gate"
                        if label.startswith("negative_")
                        else "positive_control"
                        if label.startswith("positive_")
                        else "none"
                    ),
                    bucket=heading,
                )
            )
            index += 1
    return specs


def _load_golden_anchor_ids(path: Path) -> dict[str, tuple[str, ...]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    questions = data.get("questions") if isinstance(data, dict) else data
    anchors: dict[str, tuple[str, ...]] = {}
    for item in questions or []:
        if not isinstance(item, dict):
            continue
        origin = item.get("origin") or item.get("candidate_id") or item.get("source")
        ids = ((item.get("match") or {}).get("photo_ids_any") or [])
        if origin and ids:
            anchors[str(origin)] = tuple(str(photo_id) for photo_id in ids)
    return anchors


def _build_extractor_freeze(
    question_specs: list[CandidateSpec], ollama_host: str | None
) -> dict[str, Any]:
    from eddr.query.extract import QueryExtractor

    extractor = QueryExtractor(host=ollama_host)
    rows = {}
    for spec in question_specs:
        started = time.perf_counter()
        extracted = extractor.extract(spec.query)
        rows[spec.id] = {
            "query": spec.query,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            "extracted": asdict(extracted),
        }
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "extractor": "gemma4:e2b",
        "questions": rows,
    }


def _run_executable(
    run_dir: Path,
    run_id: str,
    run: dict[str, Any],
    question_specs: list[CandidateSpec],
    food_specs: list[CandidateSpec],
    all_specs: list[CandidateSpec],
    freeze: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    from eddr.db.repository import EddrDatabase
    from eddr.query.expansion import build_query_expander
    from eddr.query.extract import ExtractedQuery
    from eddr.query.notes_bm25 import NotesBM25Index
    from eddr.query.rerankers import build_reranker
    from eddr.query.retrieval_config import get_retrieval_config
    from eddr.query.tools import QueryService
    from eddr.server.deps import NOTE_COLLECTION
    from eddr.vector.chroma_store import ChromaVectorStore
    from eddr.vision.ollama_client import OllamaVisionClient

    config = get_retrieval_config(run["variant"])
    db = EddrDatabase(args.db)
    db.initialize()
    service = QueryService(
        db,
        vector_store=ChromaVectorStore(args.chroma),
        embedding_client=OllamaVisionClient(),
        reranker=build_reranker(config.rerank),
        query_expander=build_query_expander(config.expansion, ollama_host=args.ollama_host),
        note_store=ChromaVectorStore(args.chroma, collection_name=NOTE_COLLECTION),
        notes_bm25=NotesBM25Index.from_db(db),
    )
    manifest = {
        "run_id": run_id,
        "status": "completed",
        "variant": run["variant"],
        "changed": run["changed"],
        "git_rev": _git_rev(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "hardware": _hardware(),
        "model_version": _model_version(run),
        "index_artifact": str(args.chroma),
        "index_build_command": "existing Chroma sidecar; not rebuilt in this batch",
        "seed": 42,
        "parameters": {
            "db": str(args.db),
            "chroma": str(args.chroma),
            "k": args.k,
            "query_extractor": "gemma4:e2b frozen from baseline_freeze.json",
            "text_embedding_model": "qwen3-embedding:8b",
            "base_fusion": "weighted RRF with broad lexical weight 0.25",
        },
    }
    _write_json(run_dir / "run_manifest.json", manifest)

    latencies: list[float] = []
    rows: list[dict[str, Any]] = []
    with (run_dir / "query_results.jsonl").open("w", encoding="utf-8") as fp:
        for spec in question_specs:
            extracted = ExtractedQuery(**freeze["questions"][spec.id]["extracted"])
            started = time.perf_counter()
            results = _run_frozen_search(service, extracted, spec.query, args.k)
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            latencies.append(latency_ms)
            top50 = [result.photo_id for result in results[:50]]
            row = _query_result_row(run_id, spec, top50, latency_ms, all_specs)
            rows.append(row)
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")
        for spec in food_specs:
            row = _food_bucket_row(run_id, spec)
            rows.append(row)
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = _summarize_run(run_id, rows, latencies)
    _write_json(run_dir / "summary.json", summary)
    (run_dir / "experiment.md").write_text(_render_run_report(manifest, rows, summary), encoding="utf-8")
    return summary


def _run_frozen_search(service, extracted, query: str, k: int):
    trip_ids: list[str] = []
    if extracted.countries or extracted.cities:
        trip_ids = service.db.trip_ids_for_places(extracted.countries, extracted.cities)
    return service.semantic_search_photos(
        query=query,
        k=k,
        date_from=extracted.date_from,
        date_to=extracted.date_to,
        countries=list(extracted.countries),
        cities=list(extracted.cities),
        trip_ids=trip_ids,
        keywords=list(extracted.keywords_en),
    )


def _query_result_row(
    run_id: str,
    spec: CandidateSpec,
    top50: list[str],
    latency_ms: float,
    all_specs: list[CandidateSpec],
) -> dict[str, Any]:
    expected = set(spec.expected_photo_ids)
    hard_metric = spec.eval_role == "primary" and spec.gt_status == "confirmed" and expected
    retrieved = [photo_id for photo_id in top50 if photo_id in expected]
    return {
        "run_id": run_id,
        "status": "completed",
        "question_id": spec.id,
        "query": spec.query,
        "eval_role": spec.eval_role,
        "gt_status": spec.gt_status,
        "visual": spec.visual,
        "top10": top50[:10],
        "top20": top50[:20],
        "top50": top50,
        "scores": {"rank_only": True},
        "latency_ms": latency_ms,
        "expected_photo_ids": list(spec.expected_photo_ids),
        "retrieved_expected_ids": retrieved,
        "recall_at_10": _recall(top50[:10], expected) if hard_metric else None,
        "recall_at_20": _recall(top50[:20], expected) if hard_metric else None,
        "recall_at_50": _recall(top50[:50], expected) if hard_metric else None,
        "mrr_at_10": _mrr(top50[:10], expected) if hard_metric else None,
        "ndcg_at_10": _ndcg(top50[:10], expected) if hard_metric else None,
        "food_label": spec.food_label,
        "food_false_positive_count_top20": count_food_false_positives(top50[:20], all_specs)
        if spec.fp_gate_role == "food_probe"
        else 0,
        "golden_verdict": None,
        "notes": "GT missing; ranking/provenance only" if not hard_metric else "",
    }


def _food_bucket_row(run_id: str, spec: CandidateSpec) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": "proxy_bucket",
        "question_id": spec.id,
        "query": "",
        "eval_role": spec.eval_role,
        "gt_status": spec.gt_status,
        "visual": spec.visual,
        "top10": [],
        "top20": [],
        "top50": [],
        "scores": {},
        "latency_ms": None,
        "expected_photo_ids": list(spec.expected_photo_ids),
        "retrieved_expected_ids": [],
        "recall_at_10": None,
        "recall_at_20": None,
        "recall_at_50": None,
        "mrr_at_10": None,
        "ndcg_at_10": None,
        "food_label": spec.food_label,
        "food_false_positive_count_top20": 0,
        "golden_verdict": None,
        "notes": "Proxy food bucket; used as negative/positive control metadata, not a standalone query.",
    }


def _write_blocked_run(
    run_dir: Path,
    run_id: str,
    run: dict[str, Any],
    question_specs: list[CandidateSpec],
    food_specs: list[CandidateSpec],
    args: argparse.Namespace,
) -> dict[str, Any]:
    manifest = {
        "run_id": run_id,
        "status": "blocked",
        "variant": run.get("variant"),
        "changed": run["changed"],
        "blocked_by": run["blocked_by"],
        "git_rev": _git_rev(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "hardware": _hardware(),
        "model_version": _model_version(run),
        "index_artifact": str(args.chroma),
        "index_build_command": "existing Chroma sidecar; not rebuilt in this batch",
        "seed": 42,
        "question_count": len(question_specs),
        "food_bucket_count": len(food_specs),
    }
    _write_json(run_dir / "run_manifest.json", manifest)
    blocked_row = {
        "run_id": run_id,
        "status": "blocked",
        "question_id": None,
        "query": None,
        "eval_role": "blocked",
        "gt_status": None,
        "visual": None,
        "top10": [],
        "top20": [],
        "top50": [],
        "scores": {},
        "latency_ms": None,
        "expected_photo_ids": [],
        "retrieved_expected_ids": [],
        "recall_at_10": None,
        "recall_at_20": None,
        "recall_at_50": None,
        "mrr_at_10": None,
        "ndcg_at_10": None,
        "food_label": "none",
        "food_false_positive_count_top20": 0,
        "golden_verdict": None,
        "notes": run["blocked_by"],
    }
    (run_dir / "query_results.jsonl").write_text(
        json.dumps(blocked_row, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    summary = {
        "run_id": run_id,
        "status": "blocked",
        "macro_recall_at_20": None,
        "food_false_positive_count_top20": 0,
        "p95_latency_ms": None,
        "comment": run["blocked_by"],
    }
    _write_json(run_dir / "summary.json", summary)
    (run_dir / "experiment.md").write_text(_render_blocked_report(manifest), encoding="utf-8")
    return summary


def _summarize_run(
    run_id: str, rows: list[dict[str, Any]], latencies: list[float]
) -> dict[str, Any]:
    recalls = [row["recall_at_20"] for row in rows if row["recall_at_20"] is not None]
    fp = sum(row["food_false_positive_count_top20"] for row in rows)
    return {
        "run_id": run_id,
        "status": "completed",
        "macro_recall_at_20": round(sum(recalls) / len(recalls), 3) if recalls else None,
        "food_false_positive_count_top20": fp,
        "p95_latency_ms": _p95(latencies),
        "comment": "hard recall excluded because candidate GT is missing" if not recalls else "",
    }


def _render_run_report(
    manifest: dict[str, Any], rows: list[dict[str, Any]], summary: dict[str, Any]
) -> str:
    lines = [
        f"# {manifest['run_id']} Experiment",
        "",
        "## Parameters",
        "",
        "| key | value |",
        "|---|---|",
    ]
    for key, value in manifest["parameters"].items():
        lines.append(f"| {key} | `{value}` |")
    lines += [
        "",
        "## Summary",
        "",
        f"- status: {summary['status']}",
        f"- macro recall@20: {_fmt(summary['macro_recall_at_20'])}",
        f"- food false positives@20: {summary['food_false_positive_count_top20']}",
        f"- p95 latency: {_fmt(summary['p95_latency_ms'])}ms",
        f"- opinion: {summary['comment'] or 'No hard gate regression detected in available metrics.'}",
        "",
        "## Questions",
        "",
        "| id | gt | top3 | latency | note |",
        "|---|---|---|---:|---|",
    ]
    for row in rows:
        latency = "-" if row["latency_ms"] is None else f"{row['latency_ms']}ms"
        lines.append(
            f"| {row['question_id']} | {row['gt_status']} | "
            f"{', '.join(row['top10'][:3])} | {latency} | {row['notes']} |"
        )
    return "\n".join(lines) + "\n"


def _render_blocked_report(manifest: dict[str, Any]) -> str:
    return (
        f"# {manifest['run_id']} Experiment\n\n"
        "## Status\n\n"
        "blocked\n\n"
        "## Reason\n\n"
        f"{manifest['blocked_by']}\n\n"
        "## Opinion\n\n"
        "This run should not be compared with executable variants until the missing retrieval leg exists.\n"
    )


def _recall(ranked: list[str], expected: set[str]) -> float:
    return round(len(set(ranked) & expected) / len(expected), 3)


def _mrr(ranked: list[str], expected: set[str]) -> float:
    for index, photo_id in enumerate(ranked, start=1):
        if photo_id in expected:
            return round(1 / index, 3)
    return 0.0


def _ndcg(ranked: list[str], expected: set[str]) -> float:
    dcg = sum(1 / math.log2(index + 1) for index, photo_id in enumerate(ranked, start=1) if photo_id in expected)
    ideal = sum(1 / math.log2(index + 1) for index in range(1, min(len(expected), len(ranked)) + 1))
    return round(dcg / ideal, 3) if ideal else 0.0


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 1)
    return round(statistics.quantiles(values, n=20, method="inclusive")[18], 1)


def _recommendation(run_summaries: list[dict[str, Any]]) -> str:
    completed = [row for row in run_summaries if row.get("status") == "completed"]
    if not completed:
        return "실행 가능한 variant 결과가 없으므로 production 변경은 보류한다."
    return (
        "현재 batch는 candidate GT가 대부분 missing이므로 production 채택을 결정하지 않는다. "
        "우선 `candidate_normalized.yaml`의 primary expected_photo_ids를 확정한 뒤 같은 runner로 재실행한다."
    )


def _fmt(value: Any) -> str:
    return "-" if value is None else str(value)


def _fmt_ratio(value: Any) -> str:
    return "-" if value is None else f"{value}x"


def _decision(row: dict[str, Any], latency_ratio: float | None) -> str:
    if row["status"] != "completed":
        return "not implemented"
    if latency_ratio is not None and latency_ratio > 2:
        return "reject: latency gate fail"
    if row.get("macro_recall_at_20") is None:
        return "insufficient GT"
    return "keep" if row["run_id"] == "R0_baseline" else "no production change"


def _hardware() -> dict[str, str]:
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "platform": platform.platform(),
    }


def _model_version(run: dict[str, Any]) -> dict[str, str]:
    model = {
        "query_extractor": "gemma4:e2b",
        "text_embedding": "qwen3-embedding:8b",
    }
    if run.get("variant") == "multiquery":
        model["query_expander"] = "gemma4:e2b"
    return model


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_yaml(path: Path, data: Any) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _git_rev() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())

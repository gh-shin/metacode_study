"""Regression tests for retrieval benchmark GT extraction."""

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path


def _load_bench_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "bench_retrieval.py"
    spec = importlib.util.spec_from_file_location("bench_retrieval", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_resolve_gt_uses_baseline_caption_model_by_default(tmp_path: Path):
    db_path = tmp_path / "eddr.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE photos (
            id TEXT PRIMARY KEY,
            image_path TEXT,
            duplicate_of TEXT,
            indexing_status TEXT,
            trip_id TEXT
        );
        CREATE TABLE captions (
            photo_id TEXT,
            model_id TEXT,
            text TEXT
        );
        INSERT INTO photos VALUES
            ('baseline-hit', '/photos/baseline.jpg', NULL, 'indexed', 'trip_1'),
            ('other-model-hit', '/photos/other.jpg', NULL, 'indexed', 'trip_1');
        INSERT INTO captions VALUES
            ('baseline-hit', 'gemma4:e2b', 'alpine mountain scene'),
            ('other-model-hit', 'qwen3-vl:8b', 'alpine mountain scene');
        """
    )
    conn.close()
    bench = _load_bench_module()

    ids = bench.resolve_gt(db_path, bench.GtSpec(expected=1, caption_terms=("mountain",)))

    assert ids == {"baseline-hit"}

    all_ids = bench.resolve_gt(
        db_path,
        bench.GtSpec(expected=2, caption_terms=("mountain",)),
        gt_caption_model=bench.ALL_GT_CAPTION_MODELS,
    )

    assert all_ids == {"baseline-hit", "other-model-hit"}


def test_bench_retrieval_default_output_path_matches_assignment_artifact_path():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "bench_retrieval.py"

    result = subprocess.run(
        [sys.executable, str(module_path), "--help"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert "reports/rag_quality/retrieval" in result.stdout

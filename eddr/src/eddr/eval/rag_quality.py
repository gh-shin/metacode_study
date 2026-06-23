"""Utilities for the EDDR RAG quality assignment report."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from eddr.constants import EMBEDDING_MODEL

REQUIRED_QUESTION_FIELDS = (
    "id",
    "question",
    "category",
    "assignment_type",
    "difficulty",
    "answer_type",
    "expected_signal",
    "match",
)

BASELINE_CONFIG = {
    "document_unit": "photo caption document: one caption body plus search keywords per photo",
    "chunk_size": (
        "not applicable; EDDR does not split long documents because each photo caption "
        "is already one short retrieval unit"
    ),
    "chunk_overlap": "not applicable",
    "embedding_model": EMBEDDING_MODEL,
    "vector_store": (
        "Chroma persistent sidecar at data/index/chroma, collection eddr_caption_text_v1"
    ),
    "metadata_store": "SQLite ledger at data/eddr.sqlite",
    "retriever": "QueryService.semantic_search_photos, benchmark k=20, production search cap k=20",
    "query_extractor": "gemma4:e2b via Ollama structured output, temperature 0",
    "prompt_or_instruction": (
        "baseline label controls whether qwen3 query instruction is disabled or enabled"
    ),
    "llm": "runtime external LLM is not used; local gemma4:e2b only extracts query structure",
}

EXPERIMENT_NOTES = {
    "baseline-raw-k20": {
        "changed": "질의 임베딩 instruction을 끄고 k=20으로 검색한다.",
        "expected": "가장 단순한 벡터 검색 기준선을 만든다.",
        "why": (
            "문서 단위가 짧은 사진 캡션이라 raw query도 어느 정도 동작하지만, "
            "qwen3 계열은 질의 측 instruction이 있을 때 retrieval 정렬이 안정적일 수 있다."
        ),
    },
    "exp1-instruct-default-k20": {
        "changed": "qwen3 권장 query instruction을 켠다.",
        "expected": "한국어 질의를 검색 질의로 더 명확히 임베딩해 semantic recall이 올라간다.",
        "why": (
            "문서 쪽은 raw caption이고 질의 쪽만 검색 지시문을 붙이면 query/document "
            "역할 구분이 선명해진다."
        ),
    },
    "exp2-topk50": {
        "changed": "반환 상한을 k=20에서 k=50으로 늘린다.",
        "expected": "recall은 올라가고 precision과 latency는 나빠질 수 있다.",
        "why": (
            "사진 검색 UI에서는 더 많은 후보가 날짜 lane에 흩어져 나타나므로, "
            "상위 결과 품질과 탐색 폭 사이의 트레이드오프가 생긴다."
        ),
    },
    "exp3-rrf-k20": {
        "changed": (
            "QueryExtractor가 만든 영어 keywords를 FTS5 BM25 검색에 넣고 RRF로 "
            "vector leg와 융합한다."
        ),
        "expected": (
            "road, food, milky way처럼 캡션에 직접 등장하는 단어는 보강되지만, "
            "temple, flower처럼 넓은 단어는 잡음을 만들 수 있다."
        ),
        "why": (
            "RRF는 여러 rank list를 합산하는 방식이라 정확한 lexical hit가 있을 때 "
            "강하지만, 광범위 키워드는 관련 없는 사진도 높은 점수로 끌어올린다."
        ),
    },
    "exp4-rerank-k20": {
        "changed": "상위 후보를 cross-encoder reranker로 재정렬한다.",
        "expected": (
            "정밀도가 올라갈 수 있지만 한국어 질의와 영어 캡션 조합에서는 손해가 날 수 있다."
        ),
        "why": (
            "reranker는 후보 생성 실패를 고칠 수 없고, ko-en pair 점수가 약하면 "
            "기존 embedding 순위보다 나쁜 재정렬을 만들 수 있다."
        ),
    },
}


@dataclass(frozen=True)
class QuestionSpec:
    """One assignment evaluation question."""

    id: str
    question: str
    category: str
    assignment_type: str
    difficulty: str
    answer_type: str
    expected_signal: str
    match: dict[str, Any]


@dataclass(frozen=True)
class ExperimentRecord:
    """One row from scripts/bench_retrieval.py experiments.jsonl."""

    label: str
    ts: str
    git_rev: str
    config: dict[str, Any]
    questions: list[dict[str, Any]]
    aggregate: dict[str, Any]

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ExperimentRecord:
        """Build a typed record from one JSON object."""
        return cls(
            label=str(data["label"]),
            ts=str(data.get("ts", "")),
            git_rev=str(data.get("git_rev", "unknown")),
            config=dict(data.get("config") or {}),
            questions=list(data.get("questions") or []),
            aggregate=dict(data.get("aggregate") or {}),
        )

    @property
    def mean_recall_norm(self) -> float:
        """Mean normalized recall across benchmark questions."""
        return float(self.aggregate.get("mean_recall_norm", 0.0))

    @property
    def mean_diag_recall_500(self) -> float:
        """Mean global embedding-leg recall@500."""
        return float(self.aggregate.get("mean_diag_recall@500", 0.0))

    @property
    def total_latency_s(self) -> float:
        """Total benchmark latency in seconds."""
        return float(self.aggregate.get("total_latency_s", 0.0))


def load_question_specs(path: Path) -> list[QuestionSpec]:
    """Load and validate assignment question metadata."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValueError(f"{path}: questions must be a non-empty list")

    questions: list[QuestionSpec] = []
    for index, raw in enumerate(raw_questions, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: question #{index} must be a mapping")
        for field in REQUIRED_QUESTION_FIELDS:
            if field not in raw:
                raise ValueError(f"{path}: question #{index} missing required field {field!r}")
        questions.append(
            QuestionSpec(
                id=str(raw["id"]),
                question=str(raw["question"]),
                category=str(raw["category"]),
                assignment_type=str(raw["assignment_type"]),
                difficulty=str(raw["difficulty"]),
                answer_type=str(raw["answer_type"]),
                expected_signal=str(raw["expected_signal"]),
                match=dict(raw["match"] or {}),
            )
        )
    return questions


def load_experiment_records(path: Path) -> list[ExperimentRecord]:
    """Read benchmark JSONL records in append order."""
    records: list[ExperimentRecord] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(ExperimentRecord.from_json(json.loads(line)))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
    if not records:
        raise ValueError(f"{path}: no experiment records")
    return records


def summarize_experiments(
    records: list[ExperimentRecord], baseline_label: str
) -> list[dict[str, Any]]:
    """Create comparison rows with deltas against the named baseline."""
    baseline = next((record for record in records if record.label == baseline_label), None)
    if baseline is None:
        labels = ", ".join(record.label for record in records)
        raise ValueError(f"baseline label {baseline_label!r} not found in records: {labels}")
    base_value = baseline.mean_recall_norm
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.append(
            {
                "label": record.label,
                "k": record.config.get("k"),
                "mean_recall_norm": record.mean_recall_norm,
                "delta": round(record.mean_recall_norm - base_value, 3),
                "mean_diag_recall@500": record.mean_diag_recall_500,
                "total_latency_s": record.total_latency_s,
                "rrf": bool(record.config.get("rrf")),
                "rerank": bool(record.config.get("rerank")),
            }
        )
    return rows


def render_assignment_report(
    *,
    questions: list[QuestionSpec],
    records: list[ExperimentRecord],
    baseline_label: str,
    golden_report_path: Path | None = None,
) -> str:
    """Render the Korean assignment report from question and experiment artifacts."""
    rows = summarize_experiments(records, baseline_label)
    lines: list[str] = [
        "# EDDR RAG 품질 평가 및 개선 리포트",
        "",
        "## 결론",
        "",
        _render_conclusion(rows, baseline_label),
        "",
        "## 1. 평가용 질문셋",
        "",
        f"- 총 문항 수: {len(questions)}",
        "- 문항 구성: 단순 사실 조회, 여러 문서 종합, 조건 비교, 실제 사용 자연어 질문을 포함한다.",
        "",
        "| ID | 난이도 | 유형 | 질문 | 평가 신호 |",
        "|---|---|---|---|---|",
    ]
    for question in questions:
        lines.append(
            f"| {question.id} | {question.difficulty} | {question.assignment_type} | "
            f"{question.question} | {question.expected_signal} |"
        )

    lines += [
        "",
        "## 2. Baseline RAG 설정",
        "",
        "| 항목 | 설정 |",
        "|---|---|",
    ]
    for key, value in BASELINE_CONFIG.items():
        lines.append(f"| {key} | {value} |")

    lines += [
        "",
        "## 3. 성능 개선 실험",
        "",
        (
            "- retrieval microbench는 사진 검색형 8문항(G01/G02/G03/G05/G06/G07/G09/G10)"
            "만 측정한다. 단순 날짜·사실 질문 G04/G08은 end-to-end golden 검증에서 본다."
        ),
        "",
        (
            "| label | k | RRF | rerank | mean recall norm | baseline 대비 | "
            "diag recall@500 | latency(s) |"
        ),
        "|---|---:|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['label']} | {row['k']} | {row['rrf']} | {row['rerank']} | "
            f"{row['mean_recall_norm']:.3f} | {row['delta']:+.3f} | "
            f"{row['mean_diag_recall@500']:.3f} | {row['total_latency_s']:.1f} |"
        )

    lines += [
        "",
        "## 4. 결과 분석",
        "",
    ]
    for row in rows:
        note = _note_for_label(str(row["label"]))
        lines += [
            f"### {row['label']}",
            "",
            f"- 변경한 설정: {note['changed']}",
            f"- 기대 효과: {note['expected']}",
            f"- 실제 결과: mean recall norm {row['mean_recall_norm']:.3f}, "
            f"baseline 대비 {row['delta']:+.3f}, latency {row['total_latency_s']:.1f}s.",
            f"- 해석: {note['why']}",
            "",
        ]

    if golden_report_path is not None:
        lines += _render_golden_summary(golden_report_path)

    lines += [
        "## 6. 검증 방법",
        "",
        "- 질문셋 YAML은 `eddr.query.golden.load_golden_set`으로 로드 가능해야 한다.",
        "- retrieval 실험은 `scripts/bench_retrieval.py`가 생성한 JSONL 원장을 기준으로 비교한다.",
        (
            "- end-to-end 검색 검증은 "
            "`eddr golden --golden-set docs/rag_quality/questions.yaml`로 수행한다."
        ),
    ]
    if golden_report_path is not None:
        lines.append(f"- 이번 리포트와 연결된 golden report: `{golden_report_path}`")
    lines.append("")
    return "\n".join(lines)


def _render_conclusion(rows: list[dict[str, Any]], baseline_label: str) -> str:
    best = max(rows, key=lambda row: row["mean_recall_norm"])
    baseline = next(row for row in rows if row["label"] == baseline_label)
    conclusion = (
        f"가장 좋은 실험은 `{best['label']}`이며 mean recall norm "
        f"{best['mean_recall_norm']:.3f}를 기록했다. 기준선 `{baseline['label']}` 대비 "
        f"{best['delta']:+.3f} 차이다."
    )
    same_k_rows = [
        row for row in rows if row["label"] != baseline_label and row.get("k") == baseline.get("k")
    ]
    if best.get("k") != baseline.get("k") and same_k_rows:
        same_k_best = max(same_k_rows, key=lambda row: row["mean_recall_norm"])
        conclusion += (
            f" 단, `{best['label']}`는 k={best['k']}으로 탐색 폭과 coverage를 넓힌 "
            "결과이므로 순수 품질 승리로만 해석하면 안 된다. "
            f"동일 k={baseline['k']} 비교에서 가장 강한 개선은 "
            f"`{same_k_best['label']}`이며 mean recall norm "
            f"{same_k_best['mean_recall_norm']:.3f}, 기준선 대비 "
            f"{same_k_best['delta']:+.3f}이다."
        )
    conclusion += (
        " 이 값은 캡션 LIKE 기반 proxy ground truth에 대한 상대 비교이므로, "
        "최종 판단은 golden report의 lane/상위 사진 미리보기와 함께 본다."
    )
    return conclusion


def _render_golden_summary(golden_report_path: Path) -> list[str]:
    summary = _parse_golden_report(golden_report_path)
    lines = [
        "## 5. End-to-end Golden 검증",
        "",
        f"- golden report: `{golden_report_path}`",
    ]
    if summary is None:
        lines += ["- 요약: golden report 파일을 읽을 수 없어 링크만 남긴다.", ""]
        return lines

    lines.append(
        f"- 결과: PASS {summary['pass']} / FAIL {summary['fail']} / 보류 {summary['hold']}"
    )
    failed = summary["failed"]
    if failed:
        lines.append("- 실패 문항:")
        for item in failed:
            lines.append(f"  - {item['id']}: {item['reason']}")
    else:
        lines.append("- 실패 문항: 없음")
    if summary.get("g06_passed"):
        lines.append(
            "- G06 caveat: 자동채점은 PASS였지만 `photo_ids_any`가 전체 결과 어딘가에 "
            "포함되는지만 본 약한 통과다. 상위 lane은 다른 사찰/건축 장면이 먼저 나왔고, "
            "retrieval microbench에서도 G06 recall이 낮아 데이터 부재·장소 스코프 한계가 남는다."
        )
    lines.append("")
    return lines


def _parse_golden_report(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    summary_match = re.search(
        r"\*\*PASS (?P<pass>\d+) / FAIL (?P<fail>\d+)\*\*.*보류 (?P<hold>\d+)",
        text,
    )
    if summary_match is None:
        return None

    failed: list[dict[str, str]] = []
    g06_passed = False
    sections = re.split(r"(?m)^##\s+", text)
    for section in sections:
        header, _, body = section.partition("\n")
        id_match = re.match(r"(?P<id>G\d+)\s+—", header)
        if id_match is None:
            continue
        qid = id_match.group("id")
        if qid == "G06" and "판정: **PASS**" in body:
            g06_passed = True
        if "판정: **FAIL**" not in body:
            continue
        reason = next(
            (
                line.strip().removeprefix("- ").strip()
                for line in body.splitlines()
                if line.startswith("  - ")
            ),
            "실패 사유를 golden report에서 찾지 못함",
        )
        failed.append({"id": qid, "reason": reason})

    return {
        "pass": int(summary_match.group("pass")),
        "fail": int(summary_match.group("fail")),
        "hold": int(summary_match.group("hold")),
        "failed": failed,
        "g06_passed": g06_passed,
    }


def _note_for_label(label: str) -> dict[str, str]:
    if label in EXPERIMENT_NOTES:
        return EXPERIMENT_NOTES[label]
    if "instruct" in label:
        return EXPERIMENT_NOTES["exp1-instruct-default-k20"]
    if "topk50" in label or "k50" in label:
        return EXPERIMENT_NOTES["exp2-topk50"]
    if "rrf" in label:
        return EXPERIMENT_NOTES["exp3-rrf-k20"]
    if "rerank" in label:
        return EXPERIMENT_NOTES["exp4-rerank-k20"]
    return EXPERIMENT_NOTES["baseline-raw-k20"]

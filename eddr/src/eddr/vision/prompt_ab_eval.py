"""프롬프트 A/B 결과 평가 — 라벨셋 기준으로 format/privacy/keyword 품질을 집계한다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from eddr.query.audit import CaptionAuditLabel
from eddr.query.captions import parse_caption

DEFAULT_FORBIDDEN_KEYWORDS = ("noodle", "noodles", "vermicelli", "ramen", "pasta", "naengmyeon")
DEFAULT_POSITIVE_KEYWORDS = ("cold noodle", "cold noodles", "noodle", "noodles", "naengmyeon")


@dataclass(frozen=True)
class PromptAbEvaluationRow:
    """프롬프트 출력 한 건의 평가 결과."""

    caption_model: str
    prompt_name: str
    photo_id: str
    review_label: str | None
    visual_target: bool | None
    format_ok: bool
    privacy_ok: bool
    keyword_count: int
    forbidden_keyword_hits: tuple[str, ...]
    positive_keyword_hit: bool
    error: str | None


@dataclass(frozen=True)
class PromptAbEvaluationSummary:
    """모델×프롬프트 단위 집계."""

    caption_model: str
    prompt_name: str
    rows: int
    format_ok: int
    privacy_ok: int
    negative_rows: int
    positive_rows: int
    false_forbidden_keyword_hits: int
    positive_keyword_hits: int
    positive_recall: float
    false_forbidden_rate: float
    format_pass: bool
    privacy_pass: bool
    false_forbidden_pass: bool
    positive_recall_pass: bool
    passes_gates: bool


@dataclass(frozen=True)
class PromptAbEvaluationReport:
    """프롬프트 A/B 평가 전체 결과."""

    rows: tuple[PromptAbEvaluationRow, ...]
    summaries: dict[tuple[str, str], PromptAbEvaluationSummary]


def evaluate_prompt_ab_outputs(
    *,
    paths: list[Path],
    labels: dict[str, CaptionAuditLabel],
    forbidden_keywords: tuple[str, ...] = DEFAULT_FORBIDDEN_KEYWORDS,
    positive_keywords: tuple[str, ...] = DEFAULT_POSITIVE_KEYWORDS,
    keyword_min: int = 1,
    keyword_max: int | None = None,
    positive_recall_min: float = 0.9,
    required_sections: tuple[str, ...] = (),
) -> PromptAbEvaluationReport:
    """prompt-ab JSONL 파일들을 읽어 모델×프롬프트 품질 지표를 계산한다."""
    rows: list[PromptAbEvaluationRow] = []
    for path in paths:
        for raw in _read_jsonl(path):
            photo_id = str(raw["photo_id"])
            model = str(raw["caption_model"])
            label = labels.get(photo_id)
            leaks = raw.get("leaks") or {}
            captions = raw.get("captions") or {}
            errors = raw.get("errors") or {}
            prompt_names = sorted(set(captions) | set(errors) | set(leaks))
            for prompt_name in prompt_names:
                error = errors.get(prompt_name)
                caption = str(captions.get(prompt_name) or "")
                parsed = parse_caption(caption)
                keywords = parsed.keywords
                keyword_text = " | ".join(keywords).lower()
                forbidden_hits = tuple(
                    keyword for keyword in forbidden_keywords if keyword.lower() in keyword_text
                )
                has_required_sections = all(section in caption for section in required_sections)
                keyword_count_ok = len(keywords) >= keyword_min and (
                    keyword_max is None or len(keywords) <= keyword_max
                )
                rows.append(
                    PromptAbEvaluationRow(
                        caption_model=model,
                        prompt_name=str(prompt_name),
                        photo_id=photo_id,
                        review_label=label.review_label if label else None,
                        visual_target=label.visual_target if label else None,
                        format_ok=error is None
                        and bool(keywords)
                        and keyword_count_ok
                        and has_required_sections,
                        privacy_ok=error is None and not leaks.get(prompt_name),
                        keyword_count=len(keywords),
                        forbidden_keyword_hits=forbidden_hits,
                        positive_keyword_hit=bool(label and label.visual_target)
                        and _has_any_keyword(keywords, positive_keywords),
                        error=error,
                    )
                )
    return PromptAbEvaluationReport(
        rows=tuple(rows),
        summaries=_summaries(rows, positive_recall_min=positive_recall_min),
    )


def _summaries(
    rows: list[PromptAbEvaluationRow],
    *,
    positive_recall_min: float,
) -> dict[tuple[str, str], PromptAbEvaluationSummary]:
    grouped: dict[tuple[str, str], list[PromptAbEvaluationRow]] = {}
    for row in rows:
        grouped.setdefault((row.caption_model, row.prompt_name), []).append(row)
    summaries: dict[tuple[str, str], PromptAbEvaluationSummary] = {}
    for key, group in grouped.items():
        negative_rows = sum(row.visual_target is False for row in group)
        positive_rows = sum(row.visual_target is True for row in group)
        false_forbidden_keyword_hits = sum(
            bool(row.forbidden_keyword_hits) for row in group if row.visual_target is False
        )
        positive_keyword_hits = sum(
            row.positive_keyword_hit for row in group if row.visual_target is True
        )
        positive_recall = positive_keyword_hits / positive_rows if positive_rows else 1.0
        false_forbidden_rate = (
            false_forbidden_keyword_hits / negative_rows if negative_rows else 0.0
        )
        format_ok = sum(row.format_ok for row in group)
        privacy_ok = sum(row.privacy_ok for row in group)
        format_pass = format_ok == len(group)
        privacy_pass = privacy_ok == len(group)
        false_forbidden_pass = false_forbidden_keyword_hits == 0
        positive_recall_pass = positive_recall >= positive_recall_min
        summaries[key] = PromptAbEvaluationSummary(
            caption_model=key[0],
            prompt_name=key[1],
            rows=len(group),
            format_ok=format_ok,
            privacy_ok=privacy_ok,
            negative_rows=negative_rows,
            positive_rows=positive_rows,
            false_forbidden_keyword_hits=false_forbidden_keyword_hits,
            positive_keyword_hits=positive_keyword_hits,
            positive_recall=positive_recall,
            false_forbidden_rate=false_forbidden_rate,
            format_pass=format_pass,
            privacy_pass=privacy_pass,
            false_forbidden_pass=false_forbidden_pass,
            positive_recall_pass=positive_recall_pass,
            passes_gates=format_pass
            and privacy_pass
            and false_forbidden_pass
            and positive_recall_pass,
        )
    return summaries


def _read_jsonl(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def _has_any_keyword(keywords: tuple[str, ...], needles: tuple[str, ...]) -> bool:
    keyword_text = " | ".join(keywords).lower()
    return any(needle.lower() in keyword_text for needle in needles)

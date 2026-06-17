"""골든셋 v2 자동 채점 러너 — 검색 파이프라인 직접 호출로 PASS/FAIL/보류를 판정한다 (⑧ 재정의).

문항마다 ``run_search``(routes/search.py의 라우트 코어 — 추출→trip 스코프→
semantic_search_photos→KST 그룹핑)와 동일 경로를 HTTP 비경유로 실행하고,
문항 yaml의 ``match:`` 규칙(사용자 작성, 3종 AND)을 평가한다 (prd v2 §6-b·S2).

match가 없는 문항은 "보류" — 채점 분모에서 제외하되 검색은 실행해 추출 결과·
상위 lane 미리보기를 리포트에 남긴다(사용자가 match를 작성할 입력물).
골든 규칙 작성은 사용자 몫이다 — 이 모듈은 정답을 만들지 않는다.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from eddr.query.extract import ExtractedQuery
from eddr.query.tools import PhotoSummary

if TYPE_CHECKING:  # 런타임 import는 run_golden_set 안 — server 모듈 적재를 지연한다.
    from eddr.server.routes.search import SearchLane

# 검색 1회 실행 — (추출 결과, rank 오름차순 사진). run_search(extractor, service, ·)와 동형.
SearchFn = Callable[[str], tuple[ExtractedQuery, list[PhotoSummary]]]

# v2 match 규칙 3종 — 이 외 키는 오타로 보고 FAIL 처리한다(조용한 통과 방지).
MATCH_RULES = ("photo_ids_any", "date_lane_top", "caption_contains_any")

# 리포트 노출 상한 — lane 3개·상위 사진 5장(match 작성 참고용).
_TOP_LANES = 3
_TOP_PHOTOS = 5
_CAPTION_PREVIEW = 100

# 리포트 상단 match 작성 가이드 — 예시는 전부 가상의 문항(실제 골든 정답 시사 금지).
_MATCH_GUIDE = """\
<!--
golden_set.yaml v2 match 작성 가이드 — 각 문항에 match: 키를 추가하면 자동 채점된다.
규칙 3종, 한 문항에 둘 이상 쓰면 모두 충족해야 PASS(AND). match 없는 문항은 보류(채점 제외).

1) photo_ids_any — 나열한 photo_id 중 1장 이상이 검색 결과(전체 lane)에 포함되면 충족.
   (가상 예) question: "강아지 첫 산책 사진"
   match:
     photo_ids_any: ["photos_library:00000000-AAAA-BBBB", "local:walk_001.jpg"]

2) date_lane_top — 정답 날짜 lane이 상위 N(within, 기본 1) 안에 들면 충족.
   (가상 예) question: "작년 크리스마스 트리 사진"  # 가상 정답일이 2025-12-25라면
   match:
     date_lane_top: {date: "2025-12-25", within: 3}

3) caption_contains_any — 상위 top_k(기본 10)장의 캡션(본문+키워드, 대소문자 무시)에
   words 중 1단어 이상 등장하면 충족.
   (가상 예) question: "불꽃놀이 사진"
   match:
     caption_contains_any: {words: ["firework", "fireworks"], top_k: 10}
-->"""


@dataclass(frozen=True)
class GoldenQuestion:
    """골든셋 문항 하나 (v2).

    Attributes:
        id: 문항 식별자 (예: ``G01``).
        question: 사용자 자연어 질문 원문.
        answer_type: ``fact`` 또는 ``photo_list`` — 리포트 참고용.
        expect: 사람 기준 서술 — match 작성 시 참고.
        reference: 실DB 추출 ground truth 참고치.
        match: v2 자동 채점 규칙(사용자 작성). 비어 있으면 보류.
    """

    id: str
    question: str
    answer_type: str = "photo_list"
    expect: str = ""
    reference: dict = field(default_factory=dict)
    match: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TopPhoto:
    """리포트의 상위 사진 미리보기 한 장 — match 작성 참고용.

    Attributes:
        photo_id: 사진 식별자 (photo_ids_any 규칙 작성에 쓰는 값).
        taken_at: 촬영 시각 (KST aware ISO).
        caption: 영어 캡션 본문. 없으면 None.
        keywords: 캡션 검색 키워드.
    """

    photo_id: str
    taken_at: str | None
    caption: str | None
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class GoldenRow:
    """문항 1개의 실행·채점 결과 — 러너와 리포트 작성기의 경계 객체.

    Attributes:
        id: 문항 식별자.
        question: 질문 원문.
        verdict: ``PASS``·``FAIL``·``보류``.
        reasons: 판정 근거(사람이 읽는 문장) 목록.
        interpretation: 추출 결과. 실행 오류로 추출 전 실패면 None.
        total: 검색 결과 사진 수.
        lanes: KST 달력일 lane (관련도순) — 검색 라우트와 동형(SearchLane).
        top_photos: 상위 사진 미리보기 (최대 ``_TOP_PHOTOS``장).
        elapsed_s: 문항 실행 시간(초).
    """

    id: str
    question: str
    verdict: str
    reasons: tuple[str, ...]
    interpretation: ExtractedQuery | None
    total: int
    lanes: tuple[SearchLane, ...]
    top_photos: tuple[TopPhoto, ...]
    elapsed_s: float


def load_golden_set(path: Path) -> list[GoldenQuestion]:
    """golden_set.yaml을 읽어 문항 목록을 돌려준다 — v1의 잔여 키는 무시한다."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        GoldenQuestion(
            id=item["id"],
            question=item["question"],
            answer_type=item.get("answer_type", "photo_list"),
            expect=item.get("expect", "") or "",
            reference=item.get("reference") or {},
            match=item.get("match") or {},
        )
        for item in data["questions"]
    ]


def evaluate_match(
    match: dict, results: list[PhotoSummary], groups: list[SearchLane]
) -> tuple[bool, list[str]]:
    """match 규칙(AND)을 평가한다 — (통과 여부, 규칙별 근거).

    Args:
        match: 문항의 match dict (비어 있지 않음 — 보류는 호출 전에 분기).
        results: rank 오름차순 검색 결과.
        groups: ``group_by_kst_date`` 결과(SearchLane 목록, 관련도순).

    Returns:
        (모든 규칙 충족 여부, 사람이 읽을 근거 목록). 알 수 없는 규칙 키는
        오타로 보고 FAIL 근거를 남긴다.
    """
    ok = True
    reasons: list[str] = []
    for key in match:
        if key not in MATCH_RULES:
            ok = False
            reasons.append(f"알 수 없는 match 규칙 '{key}' — 사용 가능: {', '.join(MATCH_RULES)}")
    if "photo_ids_any" in match:
        ids = match["photo_ids_any"]
        # 값 형식 검증 — 문자열을 list로 착각하면 글자 단위 순회로 거짓 판정이
        # 나므로 unknown-key와 동일하게 FAIL 근거를 남긴다(품질 리뷰 I1).
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
            ok = False
            reasons.append("photo_ids_any: 형식 오류 — 비어 있지 않은 문자열 목록이어야 함")
        else:
            wanted = set(ids)
            hit = sorted(wanted & {photo.photo_id for photo in results})
            if hit:
                reasons.append(f"photo_ids_any: 충족 — {hit[0]} 포함")
            else:
                ok = False
                reasons.append(f"photo_ids_any: 미충족 — {len(wanted)}개 중 0개 포함")
    if "date_lane_top" in match:
        rule = match["date_lane_top"]
        if not isinstance(rule, dict) or not isinstance(rule.get("date"), str):
            ok = False
            reasons.append("date_lane_top: 형식 오류 — {date: YYYY-MM-DD, within: N} 형태여야 함")
        else:
            date, within = rule["date"], int(rule.get("within", 1))
            lanes = [lane.date for lane in groups[:within]]
            if date in lanes:
                reasons.append(f"date_lane_top: 충족 — {date}가 상위 {within} lane 안")
            else:
                ok = False
                reasons.append(f"date_lane_top: 미충족 — {date} ∉ 상위 {within} lane {lanes}")
    if "caption_contains_any" in match:
        rule = match["caption_contains_any"]
        raw_words = rule.get("words") if isinstance(rule, dict) else None
        if (
            not isinstance(raw_words, list)
            or not raw_words
            or not all(isinstance(w, str) for w in raw_words)
        ):
            ok = False
            reasons.append(
                "caption_contains_any: 형식 오류 — {words: [문자열, ...], top_k: K} 형태여야 함"
            )
        else:
            words = [word.lower() for word in raw_words]
            top_k = int(rule.get("top_k", 10))
            texts = [
                " ".join([photo.caption or "", *photo.keywords]).lower()
                for photo in results[:top_k]
            ]
            hits = [word for word in words if any(word in text for text in texts)]
            if hits:
                reasons.append(f"caption_contains_any: 충족 — 상위 {top_k}장 캡션에 '{hits[0]}'")
            else:
                ok = False
                reasons.append(f"caption_contains_any: 미충족 — 상위 {top_k}장 캡션에 {words} 없음")
    return ok, reasons


def run_golden_set(
    questions: list[GoldenQuestion],
    search_fn: SearchFn,
    on_progress: Callable[[str], None] | None = None,
) -> list[GoldenRow]:
    """문항을 순차 실행·채점하고 결과 행 목록을 돌려준다.

    보류 문항도 검색은 실행한다(추출·lane 미리보기 확보). ``ConnectionError``
    (ollama 다운)는 전 문항 동일 실패이므로 그대로 전파해 즉시 중단하고,
    그 외 한 문항의 예외는 FAIL(실행 오류)로 기록하고 계속한다.

    Args:
        questions: 실행할 문항 목록.
        search_fn: 질의 → (추출 결과, 검색 결과) 함수 — 실행은
            ``run_search(extractor, service, ·)``, 테스트는 fake를 주입한다.
        on_progress: 문항 완료마다 한 줄 진행 문자열을 받는 콜백.

    Returns:
        문항별 결과 dict 목록 (verdict ∈ PASS·FAIL·보류).
    """
    from eddr.server.routes.search import group_by_kst_date, is_date_intent

    rows: list[GoldenRow] = []
    for question in questions:
        started = time.time()
        extracted: ExtractedQuery | None = None
        results: list[PhotoSummary] = []
        groups: list[SearchLane] = []
        try:
            extracted, results = search_fn(question.question)
            groups = group_by_kst_date(results, order_by_date=is_date_intent(question.question))
            if not question.match:
                verdict, reasons = "보류", ["match 규칙 미작성 — 채점 제외"]
            else:
                # evaluate_match도 try 안 — 사용자 작성 match의 형식 오류가
                # 러너 전체를 멈추고 리포트를 날리지 않게(품질 리뷰 I1).
                passed, reasons = evaluate_match(question.match, results, groups)
                verdict = "PASS" if passed else "FAIL"
        except ConnectionError:
            raise
        except Exception as exc:
            verdict, reasons = "FAIL", [f"실행 오류: {type(exc).__name__}: {exc}"]
        elapsed = round(time.time() - started, 1)
        rows.append(
            GoldenRow(
                id=question.id,
                question=question.question,
                verdict=verdict,
                reasons=tuple(reasons),
                interpretation=extracted,
                total=len(results),
                lanes=tuple(groups),
                top_photos=tuple(
                    TopPhoto(
                        photo_id=photo.photo_id,
                        taken_at=photo.taken_at,
                        caption=photo.caption,
                        keywords=photo.keywords,
                    )
                    for photo in results[:_TOP_PHOTOS]
                ),
                elapsed_s=elapsed,
            )
        )
        if on_progress is not None:
            on_progress(f"[{question.id}] {verdict} · {len(rows[-1].lanes)}lane · {elapsed}s")
    return rows


def write_report(
    rows: list[GoldenRow], report_path: Path, *, questions: list[GoldenQuestion] | None = None
) -> None:
    """자동 채점 리포트(markdown)를 쓴다 — 상단에 match 작성 가이드 주석 포함.

    보류 문항은 분모에서 제외해 표기한다. 문항별로 추출 결과·상위 lane 3개·
    상위 사진 5장(캡션 미리보기)·판정 근거를 남긴다.
    """
    by_id = {question.id: question for question in (questions or [])}
    passed = sum(1 for row in rows if row.verdict == "PASS")
    failed = sum(1 for row in rows if row.verdict == "FAIL")
    held = sum(1 for row in rows if row.verdict == "보류")
    graded = passed + failed
    lines = [
        _MATCH_GUIDE,
        "",
        "# 골든셋 v2 자동 채점 리포트",
        "",
        f"- 경로: 검색 파이프라인 직접 호출(run_search, HTTP 비경유) · 문항 {len(rows)}개",
        f"- **PASS {passed} / FAIL {failed}** (채점 분모 {graded} — 보류 {held}문항 제외)",
        "- 보류 = match 규칙 미작성. 아래 미리보기를 보고 docs/golden_set.yaml에"
        " match:를 작성하면 채점에 합류한다.",
        "",
        "| ID | 판정 | 결과 | lane | top lane | 시간(s) |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        top = row.lanes[0].date if row.lanes else "-"
        lines.append(
            f"| {row.id} | {row.verdict} | {row.total}장 | {len(row.lanes)}"
            f" | {top} | {row.elapsed_s} |"
        )
    for row in rows:
        question = by_id.get(row.id)
        lines += ["", "---", "", f"## {row.id} — {row.question}", ""]
        lines.append(f"- 판정: **{row.verdict}**")
        for reason in row.reasons:
            lines.append(f"  - {reason}")
        if question is not None and question.expect:
            lines.append(f"- 기대(사람 기준): {question.expect}")
        if question is not None:
            for key, value in question.reference.items():
                lines.append(f"- 참고({key}): {value}")
        interp = row.interpretation
        if interp is not None:
            # tuple을 list 표기로 — 기존 리포트(직렬화 dict 시절)와 같은 모양 유지.
            lines.append(
                f"- 추출: keywords_en={list(interp.keywords_en)}"
                f" · 날짜={interp.date_from}~{interp.date_to}"
                f" · countries={list(interp.countries)} · cities={list(interp.cities)}"
                f" · fallback={interp.fallback}"
            )
        lines.append(f"- 결과 {row.total}장 · lane {len(row.lanes)}개")
        if row.lanes:
            lines.append("- 상위 lane:")
            for index, lane in enumerate(row.lanes[:_TOP_LANES], start=1):
                ids = ", ".join(photo.photo_id for photo in lane.photos[:3])
                lines.append(
                    f"  {index}. {lane.date or '날짜 미상'} · {lane.place or '-'}"
                    f" · {len(lane.photos)}장 — {ids}"
                )
        if row.top_photos:
            lines.append("- 상위 사진(match 작성 참고):")
            for index, photo in enumerate(row.top_photos, start=1):
                caption = (photo.caption or "").replace("\n", " ")
                if len(caption) > _CAPTION_PREVIEW:
                    caption = caption[:_CAPTION_PREVIEW] + "…"
                day = (photo.taken_at or "")[:10] or "날짜 미상"
                keywords = ", ".join(photo.keywords)
                lines.append(f"  {index}. `{photo.photo_id}` · {day} — {caption}")
                if keywords:
                    lines.append(f"     키워드: {keywords}")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

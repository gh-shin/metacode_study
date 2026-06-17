"""질의 추출 벤치 — 골든셋 + 상대날짜 변형의 추출 결과를 사람 리뷰용 표로 남긴다.

D26 M3 선행 게이트(prd.md v2 §7): bench_extract **사람 리뷰** 선검증 전 본격 코딩 금지.
docs/golden_set.yaml의 질문 10건(읽기 전용)과 내장 상대날짜 변형 10건을 실 ollama
gemma4:e2b로 순차 추출하고 지연을 측정해
``reports/extract/YYYYMMDD_HHMM_extract_bench.md`` 표로 기록한다.
판정 칸은 비워 둔다 — 정답 판단은 사용자 몫(골든셋 규약).

실행 (repo 루트):
    .venv/bin/python scripts/bench_extract.py
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from eddr.query.extract import EXTRACT_MODEL, ExtractedQuery, QueryExtractor

KST = ZoneInfo("Asia/Seoul")
REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_PATH = REPO_ROOT / "docs" / "golden_set.yaml"
REPORT_DIR = REPO_ROOT / "reports" / "extract"

# 상대날짜·절대날짜 해석을 보는 내장 변형 — 골든셋과 달리 코드에 고정한다.
RELATIVE_DATE_VARIANTS: tuple[tuple[str, str], ...] = (
    ("V01", "작년 여름 바다"),
    ("V02", "재작년 가을 단풍 산"),
    ("V03", "지난달에 먹은 음식"),
    ("V04", "2019년 봄 벚꽃"),
    ("V05", "올해 초에 눈 온 날"),
    ("V06", "3년 전 여행"),
    ("V07", "작년 크리스마스"),
    ("V08", "이번 여름 휴가"),
    ("V09", "지지난 주말 나들이"),
    ("V10", "어제 찍은 사진"),
)


def load_golden_questions() -> list[tuple[str, str]]:
    """골든셋 yaml에서 (id, question) 목록을 읽는다 — 파일은 절대 수정하지 않는다."""
    data = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    return [(q["id"], q["question"]) for q in data["questions"]]


def _cell(text: str) -> str:
    """마크다운 표 셀 텍스트를 이스케이프한다(빈 값은 — 처리)."""
    return text.replace("|", "\\|") if text else "—"


def _row(qid: str, query: str, result: ExtractedQuery, elapsed_ms: float) -> str:
    """벤치 1문항을 마크다운 표 행으로 만든다(판정 칸은 빈 채 둔다)."""
    if result.date_from is None and result.date_to is None:
        date_range = "—"
    else:
        date_range = f"{result.date_from or '·'} ~ {result.date_to or '·'}"
    cells = [
        qid,
        _cell(query),
        _cell(", ".join(result.keywords_en)),
        date_range,
        _cell(", ".join(result.countries)),
        _cell(", ".join(result.cities)),
        "True" if result.fallback else "False",
        f"{elapsed_ms:,.0f}",
        " ",  # 판정 — 사용자 기입
    ]
    return "| " + " | ".join(cells) + " |"


def write_report(rows: list[tuple[str, str, ExtractedQuery, float]], now: datetime) -> Path:
    """추출 결과를 사람 리뷰용 마크다운 리포트로 기록한다."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{now:%Y%m%d_%H%M}_extract_bench.md"
    fallback_count = sum(1 for _, _, result, _ in rows if result.fallback)
    avg_ms = sum(ms for _, _, _, ms in rows) / len(rows)
    lines = [
        "# 질의 추출 벤치 — 사람 리뷰용 (D26 M3 선행 게이트)",
        "",
        f"- 모델: `{EXTRACT_MODEL}` (ollama structured output, temperature 0)",
        "- 입력: docs/golden_set.yaml 질문(G) + 내장 상대날짜 변형(V)",
        f"- 실행: {now:%Y-%m-%d %H:%M} KST · 순차 호출(지연ms는 추출 1회 왕복 — 재시도 포함)",
        "- 판정 칸은 비워 둠 — 정답 판단은 사용자 몫(골든셋 규약).",
        "",
        "| ID | 질의 | keywords_en | date_from~date_to | countries | cities"
        " | fallback | 지연ms | 판정 |",
        "|---|---|---|---|---|---|---|---|---|",
        *(_row(qid, query, result, ms) for qid, query, result, ms in rows),
        "",
        f"**합계**: {len(rows)}문항 · 평균 지연 {avg_ms:,.0f}ms · 폴백 {fallback_count}건"
        f" — 오늘 날짜 {now:%Y-%m-%d} KST 기준(상대 날짜 해석 기준일)",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    """골든셋 + 변형 전 문항을 순차 추출하고 리포트를 만든다."""
    questions = load_golden_questions() + list(RELATIVE_DATE_VARIANTS)
    extractor = QueryExtractor()
    now = datetime.now(KST)
    rows: list[tuple[str, str, ExtractedQuery, float]] = []
    for qid, query in questions:
        start = time.perf_counter()
        result = extractor.extract(query)
        elapsed_ms = (time.perf_counter() - start) * 1000
        rows.append((qid, query, result, elapsed_ms))
        print(f"{qid} {elapsed_ms:8,.0f}ms fallback={result.fallback} {query}", flush=True)
    report_path = write_report(rows, now)
    print(f"\n리포트: {report_path}")


if __name__ == "__main__":
    main()

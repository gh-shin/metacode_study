"""Takeout 적재 오케스트레이터 + CLI (ADR-0005).

사용 흐름(수동 획득):
  1) Takeout에서 구글 포토 [2011..year(C)] 연도앨범 선택 → 다운로드
  2) zip을 data/google_photos/raw/ 에 둔다
  3) python -m eddr.google_takeout.ingest --coverage-start YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import zipfile
from datetime import date, datetime
from pathlib import Path

from eddr.google_takeout.stage import dedup_by_content, stage_records
from eddr.google_takeout.walk import build_records, filter_by_date

_DEFAULT_ROOT = Path("data/google_photos")


def extract_raw(raw_dir: Path, extracted_dir: Path) -> None:
    """raw/의 모든 zip을 extracted/로 푼다(이미 푼 건 덮어씀)."""
    extracted_dir.mkdir(parents=True, exist_ok=True)
    for zp in sorted(raw_dir.glob("*.zip")):
        with zipfile.ZipFile(zp) as z:
            z.extractall(extracted_dir)


def ingest(extracted_root: Path, out_dir: Path, start: date, coverage_start: date) -> int:
    """Takeout extracted/ 디렉터리를 읽어 날짜 필터·dedup 후 staged/에 복사한다.

    Args:
        extracted_root: zip을 풀어둔 루트 디렉터리.
        out_dir: staged/ 와 manifest.jsonl 이 생성될 출력 루트.
        start: 적재 하한(포함), 통상 2011-01-01.
        coverage_start: 적재 상한(제외) = 맥 Photos 보관함 시작일.

    Returns:
        manifest.jsonl 에 기록된 사진 수(dedup·날짜 필터 후 실제 staged 수).
    """
    records = build_records(extracted_root)
    total = len(records)
    no_date = sum(1 for r in records if not r.taken_at)
    in_range = filter_by_date(records, start, coverage_start)
    out_of_range = (total - no_date) - len(in_range)
    kept = dedup_by_content(in_range)
    dup_dropped = len(in_range) - len(kept)
    staged = stage_records(kept, out_dir)
    print(
        f"  walked={total} no_date_dropped={no_date} "
        f"out_of_range_dropped={out_of_range} dup_dropped={dup_dropped} staged={staged}"
    )
    return staged


def main() -> None:
    """CLI 진입점. 인자를 파싱하고 extract_raw → ingest 순으로 실행한다."""
    ap = argparse.ArgumentParser(description="Google Takeout → data/google_photos staging")
    ap.add_argument("--root", type=Path, default=_DEFAULT_ROOT)
    ap.add_argument(
        "--start",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=date(2011, 1, 1),
        help="하한(포함), 기본 2011-01-01",
    )
    ap.add_argument(
        "--coverage-start",
        required=True,
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        help="상한 C(제외) = 맥 보관함 시작일",
    )
    ap.add_argument("--skip-extract", action="store_true")
    args = ap.parse_args()

    raw, extracted = args.root / "raw", args.root / "extracted"
    if not args.skip_extract:
        extract_raw(raw, extracted)
    n = ingest(extracted, args.root, args.start, args.coverage_start)
    print(f"staged {n} photos → {args.root / 'staged'} (manifest.jsonl)")


if __name__ == "__main__":
    main()

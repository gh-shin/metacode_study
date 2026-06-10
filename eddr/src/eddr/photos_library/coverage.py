"""맥 Photos Library의 촬영일 분포를 측정해 상한 C 결정을 돕는다 (ADR-0005)."""

from __future__ import annotations

from collections import Counter
from datetime import datetime


def summarize_years(dates: list[datetime]) -> dict[int, int]:
    """촬영일 리스트 → {연도: 장수}."""
    return dict(sorted(Counter(d.year for d in dates).items()))


def query_taken_dates() -> list[datetime]:
    """Photos Library에서 이미지(동영상 제외)의 촬영일을 읽는다.

    Photos 접근 권한 필요. 권한이 없으면 osxphotos가 빈 결과/예외를 낼 수 있다.
    """
    import osxphotos

    db = osxphotos.PhotosDB()
    return [p.date for p in db.photos(movies=False) if p.date is not None]


def print_year_table(year_counts: dict[int, int]) -> None:
    """연도별 사진 수와 누적 비율을 표 형식으로 표준 출력에 출력한다.

    Args:
        year_counts: {연도: 장수} 딕셔너리 (summarize_years 반환값).
    """
    total = sum(year_counts.values())
    print(f"{'YEAR':>6} {'COUNT':>7} {'CUM%':>6}")
    cum = 0
    for year, n in year_counts.items():
        cum += n
        print(f"{year:>6} {n:>7} {100 * cum / total:>5.1f}%")
    print(f"{'TOTAL':>6} {total:>7}")


if __name__ == "__main__":
    print_year_table(summarize_years(query_taken_dates()))

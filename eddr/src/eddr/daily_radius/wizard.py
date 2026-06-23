"""setup wizard — Daily Radius 후보를 사용자가 확정·라벨·반경 편집 (D15)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from eddr.daily_radius.cluster import AreaCandidate, propose_daily_radius
from eddr.db.repository import EddrDatabase


def propose_candidates(
    db: EddrDatabase, top_n: int = 8, min_count: int = 30
) -> list[AreaCandidate]:
    """DB의 GPS 사진(중복 제외)에서 Daily Radius 후보를 만들고 대표 지명을 붙인다.

    Args:
        db: 대상 데이터베이스.
        top_n: 최대 후보 수.
        min_count: 후보 최소 사진 수.

    Returns:
        place(geocode 최빈 지명)가 채워진 AreaCandidate 리스트.
    """
    coords = db.gps_coordinates(exclude_duplicates=True)
    candidates = propose_daily_radius(coords, top_n=top_n, min_count=min_count)
    return [
        replace(
            candidate,
            place=db.majority_place_near(
                candidate.center_lat, candidate.center_lng, candidate.radius_km
            ),
        )
        for candidate in candidates
    ]


def format_candidate(index: int, total: int, candidate: AreaCandidate) -> str:
    """wizard 표시용 후보 한 줄 요약을 만든다."""
    place = candidate.place or "지명 미상"
    return (
        f"[{index}/{total}] {place} — {candidate.photo_count}장,"
        f" 중심 ({candidate.center_lat:.4f}, {candidate.center_lng:.4f}),"
        f" 제안 반경 {candidate.radius_km}km"
    )


def run_wizard(
    db: EddrDatabase,
    candidates: list[AreaCandidate],
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> int:
    """후보를 순회하며 사용자 확정을 받아 daily_radius_areas에 저장한다.

    후보마다 y(라벨·반경 입력) / n(건너뜀) / q(즉시 종료)를 받는다. 확정이
    1건 이상이면 기존 영역을 전체 교체한다(재실행 멱등). EOF(비대화 환경)는
    저장 없이 중단한다.

    Args:
        db: 대상 데이터베이스.
        candidates: propose_candidates가 만든 후보 리스트.
        input_fn: 입력 함수 (테스트 주입용).
        print_fn: 출력 함수 (테스트 주입용).

    Returns:
        저장된 영역 수.
    """
    confirmed: list[tuple[str, float, float, float]] = []
    total = len(candidates)
    try:
        for index, candidate in enumerate(candidates, start=1):
            print_fn(format_candidate(index, total, candidate))
            answer = input_fn("  일상 반경에 포함? [y/n/q] ").strip().lower()
            if answer == "q":
                break
            if answer != "y":
                continue
            label = input_fn("  라벨 (예: 집/직장/본가): ").strip() or (
                candidate.place or f"영역{index}"
            )
            radius_raw = input_fn(f"  반경(km) [{candidate.radius_km}]: ").strip()
            radius_km = float(radius_raw) if radius_raw else candidate.radius_km
            confirmed.append((label, candidate.center_lat, candidate.center_lng, radius_km))
    except EOFError:
        print_fn("입력이 닫혀 저장 없이 종료합니다 (--propose-only로 후보만 볼 수 있음).")
        return 0
    if confirmed:
        db.replace_daily_radius_areas(confirmed)
        print_fn(f"daily_radius_areas {len(confirmed)}건 저장 완료.")
    else:
        print_fn("저장된 영역 없음 — 기존 데이터 유지.")
    return len(confirmed)

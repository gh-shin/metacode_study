import pytest

from eddr.daily_radius.cluster import haversine_km, propose_daily_radius


def _spread(center_lat: float, center_lng: float, count: int) -> list[tuple[float, float]]:
    """중심 주변 ±0.015°(약 1.5km) 격자에 결정적으로 흩뿌린 좌표를 만든다."""
    coords = []
    for i in range(count):
        coords.append(
            (
                center_lat + ((i % 7) - 3) * 0.005,
                center_lng + ((i % 5) - 2) * 0.005,
            )
        )
    return coords


def test_haversine_seoul_busan_about_325km():
    assert haversine_km(37.5665, 126.9780, 35.1796, 129.0756) == pytest.approx(325, abs=5)


def test_propose_finds_two_dense_clusters_in_order():
    seoul = _spread(37.50, 127.03, 400)
    busan = _spread(35.18, 129.08, 100)

    candidates = propose_daily_radius(seoul + busan, min_count=30)

    assert len(candidates) == 2
    assert candidates[0].photo_count == 400
    assert candidates[0].center_lat == pytest.approx(37.50, abs=0.02)
    assert candidates[0].center_lng == pytest.approx(127.03, abs=0.02)
    assert candidates[1].photo_count == 100
    assert candidates[1].center_lat == pytest.approx(35.18, abs=0.02)


def test_propose_merges_adjacent_cells_into_one_candidate():
    coords = _spread(37.50, 127.03, 200)

    candidates = propose_daily_radius(coords, min_count=30)

    assert len(candidates) == 1
    assert candidates[0].photo_count == 200
    assert candidates[0].radius_km >= 1.0


def test_propose_filters_sparse_noise_with_min_count():
    dense = _spread(37.50, 127.03, 100)
    noise = [(64.1 + i * 0.5, -21.9 + i * 0.5) for i in range(10)]

    candidates = propose_daily_radius(dense + noise, min_count=30)

    assert len(candidates) == 1


def test_propose_respects_top_n():
    clusters = []
    for k in range(5):
        clusters += _spread(10.0 + k * 2, 100.0 + k * 2, 50)

    candidates = propose_daily_radius(clusters, top_n=3, min_count=30)

    assert len(candidates) == 3


def test_propose_orders_by_merged_total_not_peak_cell():
    """피크 셀은 작아도 병합 총량이 큰 클러스터가 앞에 와야 한다."""
    # A: 단일 셀 50장 (피크 50, 총 50)
    single_peak = [(37.50, 127.03)] * 50
    # B: 인접 3셀 각 30장 (피크 30, 총 90) — A보다 피크는 작고 총량은 크다
    wide_cluster = [(35.18, 129.08)] * 30 + [(35.19, 129.08)] * 30 + [(35.18, 129.09)] * 30

    candidates = propose_daily_radius(single_peak + wide_cluster, min_count=30)

    assert [c.photo_count for c in candidates] == [90, 50]


def test_propose_empty_input():
    assert propose_daily_radius([]) == []

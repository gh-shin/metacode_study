from datetime import datetime

from eddr.photos_library.coverage import summarize_years


def test_summarize_years_counts_per_year():
    dates = [
        datetime(2015, 1, 1),
        datetime(2015, 6, 1),
        datetime(2021, 3, 1),
        datetime(2021, 4, 1),
        datetime(2021, 5, 1),
    ]
    assert summarize_years(dates) == {2015: 2, 2021: 3}


def test_summarize_years_empty():
    assert summarize_years([]) == {}

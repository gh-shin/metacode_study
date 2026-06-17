from pathlib import Path

from eddr.daily_radius.cluster import AreaCandidate
from eddr.daily_radius.wizard import propose_candidates, run_wizard
from eddr.db.repository import EddrDatabase, PhotoRecord


def _make_db(tmp_path: Path) -> EddrDatabase:
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    return db


class _ScriptedInput:
    def __init__(self, answers: list[str]):
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0)


def _candidate(lat: float, lng: float, count: int, place: str | None = None) -> AreaCandidate:
    return AreaCandidate(
        center_lat=lat, center_lng=lng, radius_km=3.0, photo_count=count, place=place
    )


def test_propose_candidates_excludes_duplicates_and_enriches_place(tmp_path: Path):
    db = _make_db(tmp_path)
    for i in range(40):
        db.upsert_photo(
            PhotoRecord(
                id=f"photos_library:u{i}",
                source="photos_library",
                source_uri=f"u{i}",
                latitude=37.50 + (i % 5) * 0.001,
                longitude=127.03 + (i % 5) * 0.001,
            )
        )
        db.update_photo_geo(f"photos_library:u{i}", "대한민국", "서울특별시", "강남구")
    # 같은 자리의 중복 행 — 밀도에 이중 계산되지 않아야 한다
    db.upsert_photo(
        PhotoRecord(
            id="local:dup",
            source="local",
            source_uri="dup",
            latitude=37.50,
            longitude=127.03,
        )
    )
    with db.connect() as conn:
        conn.execute("UPDATE photos SET duplicate_of = 'photos_library:u0' WHERE id = 'local:dup'")

    candidates = propose_candidates(db, min_count=30)

    assert len(candidates) == 1
    assert candidates[0].photo_count == 40
    assert candidates[0].place == "서울특별시 강남구"


def test_run_wizard_saves_confirmed_areas_with_label_and_radius(tmp_path: Path):
    db = _make_db(tmp_path)
    answers = _ScriptedInput(["y", "집", "2.5", "n"])
    candidates = [
        _candidate(37.50, 127.03, 400, place="서울특별시 강남구"),
        _candidate(35.18, 129.08, 100),
    ]

    saved = run_wizard(db, candidates, input_fn=answers, print_fn=lambda s: None)

    assert saved == 1
    areas = db.list_daily_radius_areas()
    assert len(areas) == 1
    area = areas[0]
    assert area.label == "집"
    assert area.center_lat == 37.50
    assert area.radius_km == 2.5


def test_run_wizard_empty_radius_keeps_suggestion(tmp_path: Path):
    db = _make_db(tmp_path)
    answers = _ScriptedInput(["y", "직장", ""])

    run_wizard(db, [_candidate(37.40, 127.10, 200)], input_fn=answers, print_fn=lambda s: None)

    assert db.list_daily_radius_areas()[0].radius_km == 3.0


def test_run_wizard_quit_stops_and_replaces_previous_areas(tmp_path: Path):
    db = _make_db(tmp_path)
    run_wizard(
        db,
        [_candidate(37.50, 127.03, 400)],
        input_fn=_ScriptedInput(["y", "옛집", ""]),
        print_fn=lambda s: None,
    )

    saved = run_wizard(
        db,
        [_candidate(36.35, 127.38, 300), _candidate(35.18, 129.08, 100)],
        input_fn=_ScriptedInput(["y", "본가", "", "q"]),
        print_fn=lambda s: None,
    )

    assert saved == 1
    areas = db.list_daily_radius_areas()
    assert [a.label for a in areas] == ["본가"]


def test_run_wizard_eof_aborts_without_saving(tmp_path: Path):
    db = _make_db(tmp_path)

    def raises_eof(prompt: str) -> str:
        raise EOFError

    run_wizard(
        db,
        [_candidate(37.50, 127.03, 400)],
        input_fn=_ScriptedInput(["y", "집", ""]),
        print_fn=lambda s: None,
    )
    saved = run_wizard(
        db, [_candidate(35.18, 129.08, 100)], input_fn=raises_eof, print_fn=lambda s: None
    )

    assert saved == 0
    assert [a.label for a in db.list_daily_radius_areas()] == ["집"]

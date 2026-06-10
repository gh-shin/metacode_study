from pathlib import Path

from eddr.cli import main
from eddr.db.repository import EddrDatabase


def test_cli_db_init_creates_sqlite_schema(tmp_path: Path):
    db_path = tmp_path / "eddr.sqlite"

    exit_code = main(["db", "init", "--db", str(db_path)])

    assert exit_code == 0
    assert db_path.exists()
    db = EddrDatabase(db_path)
    assert db.count_photos() == 0

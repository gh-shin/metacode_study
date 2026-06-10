from pathlib import Path

from eddr.photos_export.osxphotos_export import build_export_command


def test_build_export_command_uses_download_missing_and_stable_report_paths(tmp_path: Path):
    command = build_export_command(
        export_dir=tmp_path / "photos_export",
        export_db=tmp_path / "photos_export.db",
        report_csv=tmp_path / "photos_export.csv",
    )

    assert command[:2] == ["osxphotos", "export"]
    assert str(tmp_path / "photos_export") in command
    assert "--download-missing" in command
    assert "--use-photokit" in command
    assert "--update" in command
    assert "--exportdb" in command
    assert str(tmp_path / "photos_export.db") in command
    assert "--report" in command
    assert str(tmp_path / "photos_export.csv") in command


def test_build_export_command_uses_valid_only_photos_flag_not_skip_movies(tmp_path: Path):
    # Regression: osxphotos has no --skip-movies option; exporting only photos
    # (skipping videos) uses --only-photos. The invalid flag aborted export at runtime.
    command = build_export_command(
        export_dir=tmp_path / "photos_export",
        export_db=tmp_path / "photos_export.db",
        report_csv=tmp_path / "photos_export.csv",
    )

    assert "--only-photos" in command
    assert "--skip-movies" not in command

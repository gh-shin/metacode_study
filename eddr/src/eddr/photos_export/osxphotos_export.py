"""macOS Photos Library를 osxphotos CLI로 내보내는 명령 빌더와 실행기."""

from __future__ import annotations

import subprocess
from pathlib import Path


def build_export_command(export_dir: Path, export_db: Path, report_csv: Path) -> list[str]:
    """osxphotos export 명령 인수 목록을 생성한다.

    --only-photos(동영상 제외), --update(증분), UUID 파일명으로 고정한다.

    Args:
        export_dir: 사진을 저장할 출력 디렉터리.
        export_db: osxphotos 내부 export DB 경로.
        report_csv: 내보내기 결과를 기록할 CSV 리포트 경로.

    Returns:
        subprocess에 직접 전달할 수 있는 명령 인수 문자열 목록.
    """
    return [
        "osxphotos",
        "export",
        str(export_dir),
        "--download-missing",
        "--use-photokit",
        "--update",
        "--only-photos",
        "--not-hidden",
        "--filename",
        "{uuid}",
        "--exportdb",
        str(export_db),
        "--report",
        str(report_csv),
    ]


def run_export(export_dir: Path, export_db: Path, report_csv: Path) -> subprocess.CompletedProcess:
    """필요한 디렉터리를 생성한 후 osxphotos export를 실행한다.

    Args:
        export_dir: 사진을 저장할 출력 디렉터리.
        export_db: osxphotos 내부 export DB 경로.
        report_csv: 내보내기 결과를 기록할 CSV 리포트 경로.

    Returns:
        완료된 프로세스 정보(subprocess.CompletedProcess).

    Raises:
        subprocess.CalledProcessError: osxphotos 프로세스가 비정상 종료된 경우.
    """
    export_dir.mkdir(parents=True, exist_ok=True)
    export_db.parent.mkdir(parents=True, exist_ok=True)
    report_csv.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        build_export_command(export_dir, export_db, report_csv),
        check=True,
        text=True,
    )

"""BLAKE3 내부 dedup + staged/ 복사 + manifest.jsonl (ADR-0005)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from blake3 import blake3

from eddr.google_takeout.walk import MediaRecord


def blake3_hex(path: Path) -> str:
    """파일을 1 MiB 단위로 스트리밍 해시해 BLAKE3 16진수 다이제스트를 반환한다.

    Args:
        path: 해시할 파일 경로.

    Returns:
        64자 BLAKE3 16진수 문자열.
    """
    h = blake3()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dedup_by_content(records: list[MediaRecord]) -> list[MediaRecord]:
    """content_hash별 1장. source_uri 정렬 순서로 먼저 오는 것을 보관."""
    seen: dict[str, MediaRecord] = {}
    for r in sorted(records, key=lambda r: r.source_uri):
        key = blake3_hex(r.path)
        seen.setdefault(key, r)
    return list(seen.values())


def stage_records(records: list[MediaRecord], out_dir: Path) -> int:
    """레코드 목록을 out_dir/staged/ 에 복사하고 manifest.jsonl 을 기록한다.

    이미 staged/ 에 동일 content_hash 파일이 있으면 복사를 건너뛴다.
    manifest.jsonl 은 매번 덮어쓴다.

    Args:
        records: 복사할 MediaRecord 목록(dedup 완료 상태 권장).
        out_dir: staged/ 와 manifest.jsonl 이 생성될 출력 루트.

    Returns:
        manifest.jsonl 에 기록된 항목 수.
    """
    staged_dir = out_dir / "staged"
    staged_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.jsonl"
    written = 0
    with manifest.open("w", encoding="utf-8") as mf:
        for r in records:
            h = blake3_hex(r.path)
            dest = staged_dir / f"{h}{r.path.suffix.lower()}"
            if not dest.exists():
                shutil.copy2(r.path, dest)
            mf.write(
                json.dumps(
                    {
                        "source": "google_takeout",
                        "source_uri": r.source_uri,
                        "staged_path": str(dest),
                        "content_hash": h,
                        "taken_at": r.taken_at.isoformat() if r.taken_at else None,
                        "latitude": r.latitude,
                        "longitude": r.longitude,
                        "description": r.description,
                        "people": r.people,
                        "original_filename": r.original_filename,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            written += 1
    return written

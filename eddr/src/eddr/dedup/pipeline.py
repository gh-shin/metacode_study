"""해시 백필 + cross-source 동일 해시 마킹 파이프라인 (PLAN §4.2)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from eddr.db.repository import EddrDatabase
from eddr.dedup.hashes import blake3_hex, dhash_hex

# canonical 선택 우선순위 — D4(Photos Library가 SoT) 기준 (PLAN §4.2).
CANONICAL_SOURCE_PRIORITY = ("photos_library", "local", "google_takeout")


@dataclass(frozen=True)
class HashBackfillReport:
    """해시 백필 결과 요약.

    Attributes:
        processed: 해시가 갱신된 사진 수.
        dhash_failed: content hash는 채웠으나 이미지 디코드 불가로 dHash를 못 채운 수.
        errors: 파일 미존재 등으로 실패한 수 (index_errors 기록).
    """

    processed: int = 0
    dhash_failed: int = 0
    errors: int = 0


@dataclass(frozen=True)
class DedupMarkReport:
    """cross-source dedup 마킹 결과 요약.

    Attributes:
        groups: 소스 2개 이상이 공유한 content_hash 그룹 수.
        marked: duplicate_of가 기록된 사진 수.
    """

    groups: int = 0
    marked: int = 0


def backfill_hashes(db: EddrDatabase, limit: int | None = None) -> HashBackfillReport:
    """해시 누락 사진의 BLAKE3·dHash를 계산해 채운다.

    이미 있는 해시는 보존하고 비어 있는 쪽만 계산한다. 파일을 읽지 못하면
    index_errors(stage='hash_backfill')에 기록하고 다음 행으로 진행한다.

    Args:
        db: 대상 데이터베이스.
        limit: 처리할 최대 사진 수. None이면 전체.

    Returns:
        처리·dHash 실패·오류 건수를 담은 HashBackfillReport.
    """
    processed = dhash_failed = errors = 0
    for photo in db.photos_missing_hashes(limit):
        path = Path(photo.image_path)
        try:
            content_hash = photo.content_hash or blake3_hex(path)
        except OSError as exc:
            db.record_error(photo.id, "hash_backfill", f"{path}: {exc}")
            errors += 1
            continue
        perceptual_hash = photo.perceptual_hash or dhash_hex(path)
        if perceptual_hash is None:
            dhash_failed += 1
        db.update_photo_hashes(photo.id, content_hash=content_hash, perceptual_hash=perceptual_hash)
        processed += 1
    return HashBackfillReport(processed=processed, dhash_failed=dhash_failed, errors=errors)


def mark_cross_source_duplicates(db: EddrDatabase) -> DedupMarkReport:
    """BLAKE3 동일 cross-source 그룹에서 canonical 외 행에 duplicate_of를 기록한다.

    기존 마킹을 전부 지우고 재계산하므로 재실행해도 결과가 동일하다.

    Args:
        db: 대상 데이터베이스.

    Returns:
        그룹·마킹 건수를 담은 DedupMarkReport.
    """
    report = db.apply_cross_source_dedup(CANONICAL_SOURCE_PRIORITY)
    return DedupMarkReport(groups=report.groups, marked=report.marked)

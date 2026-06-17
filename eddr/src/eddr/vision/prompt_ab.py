"""프롬프트 A/B 비교 배치 — 두 프롬프트 변형의 캡션을 동시 생성해 JSONL로 저장한다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from eddr.db.repository import EddrDatabase, PhotoRecord
from eddr.vision.prompt import (
    P3_HYBRID_PROMPT_NAME,
    P3_HYBRID_V2_PROMPT_NAME,
    find_sensitive_metadata_leaks,
)


class PromptAbVisionClient(Protocol):
    """A/B 비교에 필요한 프롬프트별 캡션 생성 기능을 정의하는 프로토콜."""

    caption_model: str

    def caption_photo(self, photo: PhotoRecord, prompt_name: str | None = None) -> str:
        """지정한 프롬프트로 사진 한 장의 캡션을 생성한다."""
        ...


@dataclass(frozen=True)
class PromptAbReport:
    """A/B 배치 실행 결과 — 성공·실패 건수와 출력 파일 경로를 담는다."""

    processed: int
    failed: int
    output_path: Path


def run_prompt_ab(
    db: EddrDatabase,
    vision_client: PromptAbVisionClient,
    limit: int,
    output_path: Path,
    prompt_names: tuple[str, ...] | None = None,
    photo_ids: tuple[str, ...] | None = None,
) -> PromptAbReport:
    """미처리 사진을 층화 샘플링해 두 프롬프트 변형으로 캡션을 생성하고 JSONL 파일에 저장한다.

    기본값은 ``P3_HYBRID_PROMPT_NAME``과 ``P3_HYBRID_V2_PROMPT_NAME`` 두 프롬프트다.
    ``prompt_names``를 넘기면 지정한 프롬프트들을 순서대로 호출한다. 모든 캡션이
    성공해야 processed로 집계되며, 어느 하나라도 예외가 발생하면 failed로 집계된다.
    ``photo_ids``를 넘기면 pending 여부와 무관하게 해당 사진들을 순서대로 재실험한다.

    Args:
        db: EDDR SQLite 데이터베이스 접근 객체.
        vision_client: 프롬프트별 캡션 생성을 수행할 비전 클라이언트.
        limit: 이번 배치에서 처리할 최대 사진 수.
        output_path: 결과를 기록할 JSONL 파일 경로(부모 디렉터리는 자동 생성됨).
        prompt_names: 비교할 프롬프트 이름 목록. None이면 기본 두 프롬프트.
        photo_ids: 특정 사진 id 목록. None이면 기존 층화 pending 샘플을 사용한다.

    Returns:
        처리 성공·실패 건수와 출력 파일 경로를 담은 ``PromptAbReport``.
    """
    processed = failed = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_names = prompt_names or (P3_HYBRID_PROMPT_NAME, P3_HYBRID_V2_PROMPT_NAME)

    with output_path.open("w", encoding="utf-8") as handle:
        for photo in _prompt_ab_photos(db, limit=limit, photo_ids=photo_ids):
            image_path = Path(photo.image_path or "")
            if not image_path.exists():
                failed += 1
                _write_jsonl(
                    handle,
                    {
                        "photo_id": photo.id,
                        "image_path": photo.image_path,
                        "error": f"image_path does not exist: {image_path}",
                    },
                )
                continue

            captions: dict[str, str] = {}
            leaks: dict[str, list[str]] = {}
            errors: dict[str, str] = {}
            for prompt_name in prompt_names:
                try:
                    caption = vision_client.caption_photo(photo, prompt_name=prompt_name)
                    captions[prompt_name] = caption
                    leaks[prompt_name] = find_sensitive_metadata_leaks(caption, photo)
                except Exception as exc:
                    errors[prompt_name] = str(exc)
                    leaks[prompt_name] = []

            if errors:
                failed += 1
            else:
                processed += 1

            _write_jsonl(
                handle,
                {
                    "photo_id": photo.id,
                    "source": photo.source,
                    "image_path": photo.image_path,
                    "taken_at": photo.taken_at,
                    "caption_model": vision_client.caption_model,
                    "captions": captions,
                    "leaks": leaks,
                    "errors": errors,
                },
            )

    return PromptAbReport(processed=processed, failed=failed, output_path=output_path)


def _prompt_ab_photos(
    db: EddrDatabase, *, limit: int, photo_ids: tuple[str, ...] | None
) -> list[PhotoRecord]:
    if photo_ids is None:
        return list(db.pending_vision_photos_stratified(limit=limit))
    photos: list[PhotoRecord] = []
    for photo_id in photo_ids:
        photo = db.get_photo(photo_id)
        if photo is not None:
            photos.append(photo)
        if len(photos) >= limit:
            break
    return photos


def _write_jsonl(handle, row: dict) -> None:
    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

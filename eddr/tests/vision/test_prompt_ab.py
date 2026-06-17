import json
from pathlib import Path

from eddr.db.repository import EddrDatabase, PhotoRecord
from eddr.vision.prompt import P3_HYBRID_PROMPT_NAME, P3_HYBRID_V2_PROMPT_NAME
from eddr.vision.prompt_ab import run_prompt_ab


class FakePromptClient:
    caption_model = "fake-caption"

    def caption_photo(self, photo: PhotoRecord, prompt_name: str | None = None) -> str:
        return f"Caption: {prompt_name} for {Path(photo.image_path or '').name}"


def test_run_prompt_ab_writes_legacy_and_metadata_captions_without_upserting(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    image = tmp_path / "image.jpg"
    image.write_bytes(b"image")
    db.upsert_photo(
        PhotoRecord(
            id="local:abc",
            source="local",
            source_uri=str(image),
            image_path=str(image),
            content_hash="abc",
            indexing_status="meta_done",
        )
    )

    out = tmp_path / "prompt_ab.jsonl"
    report = run_prompt_ab(db=db, vision_client=FakePromptClient(), limit=30, output_path=out)

    assert report.processed == 1
    assert report.failed == 0
    assert db.count_captions() == 0
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["photo_id"] == "local:abc"
    assert row["captions"][P3_HYBRID_PROMPT_NAME] == "Caption: p3_hybrid for image.jpg"
    assert row["captions"][P3_HYBRID_V2_PROMPT_NAME] == "Caption: p3_hybrid_v2 for image.jpg"
    assert row["leaks"] == {P3_HYBRID_PROMPT_NAME: [], P3_HYBRID_V2_PROMPT_NAME: []}


def test_run_prompt_ab_uses_deterministic_stratified_photo_selection(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    for idx in range(3):
        image = tmp_path / f"local-{idx}.jpg"
        image.write_bytes(b"image")
        db.upsert_photo(
            PhotoRecord(
                id=f"local:{idx}",
                source="local",
                source_uri=str(image),
                image_path=str(image),
                taken_at=f"2020-01-0{idx + 1}T00:00:00+00:00",
                width=1200,
                height=800,
                indexing_status="meta_done",
            )
        )
    takeout = tmp_path / "takeout.jpg"
    takeout.write_bytes(b"image")
    db.upsert_photo(
        PhotoRecord(
            id="google_takeout:1",
            source="google_takeout",
            source_uri=str(takeout),
            image_path=str(takeout),
            taken_at="2022-01-01T00:00:00+00:00",
            latitude=33.450701,
            longitude=126.570667,
            width=800,
            height=1200,
            indexing_status="meta_done",
        )
    )

    out = tmp_path / "prompt_ab.jsonl"
    report = run_prompt_ab(db=db, vision_client=FakePromptClient(), limit=2, output_path=out)

    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert report.processed == 2
    assert [row["photo_id"] for row in rows] == ["google_takeout:1", "local:0"]


def test_run_prompt_ab_can_compare_selected_prompt_names(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    image = tmp_path / "food.jpg"
    image.write_bytes(b"image")
    db.upsert_photo(
        PhotoRecord(
            id="local:food",
            source="local",
            source_uri=str(image),
            image_path=str(image),
            indexing_status="meta_done",
        )
    )

    out = tmp_path / "prompt_ab.jsonl"
    report = run_prompt_ab(
        db=db,
        vision_client=FakePromptClient(),
        limit=1,
        output_path=out,
        prompt_names=("p3_hybrid_food_guard",),
    )

    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert report.processed == 1
    assert row["captions"] == {"p3_hybrid_food_guard": "Caption: p3_hybrid_food_guard for food.jpg"}


def test_run_prompt_ab_can_target_explicit_photo_ids_even_if_already_captioned(tmp_path: Path):
    db = EddrDatabase(tmp_path / "eddr.sqlite")
    db.initialize()
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"image")
    second.write_bytes(b"image")
    for photo_id, image in (("local:first", first), ("local:second", second)):
        db.upsert_photo(
            PhotoRecord(
                id=photo_id,
                source="local",
                source_uri=str(image),
                image_path=str(image),
                indexing_status="caption_done",
            )
        )
        db.upsert_caption(photo_id, "gemma4:e2b", "en", "Existing caption.")

    out = tmp_path / "prompt_ab.jsonl"
    report = run_prompt_ab(
        db=db,
        vision_client=FakePromptClient(),
        limit=30,
        output_path=out,
        prompt_names=("p3_hybrid_food_guard",),
        photo_ids=("local:second", "missing", "local:first"),
    )

    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert report.processed == 2
    assert [row["photo_id"] for row in rows] == ["local:second", "local:first"]

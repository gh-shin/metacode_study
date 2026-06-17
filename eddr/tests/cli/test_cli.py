import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from eddr.cli import main
from eddr.db.repository import EddrDatabase, PhotoRecord


def test_cli_db_init_creates_sqlite_schema(tmp_path: Path):
    db_path = tmp_path / "eddr.sqlite"

    exit_code = main(["db", "init", "--db", str(db_path)])

    assert exit_code == 0
    assert db_path.exists()
    db = EddrDatabase(db_path)
    assert db.count_photos() == 0


def test_cli_dedup_backfill_and_mark(tmp_path: Path, capsys):
    db_path = tmp_path / "eddr.sqlite"
    img = tmp_path / "a.png"
    Image.new("L", (32, 32), color=128).save(img)
    db = EddrDatabase(db_path)
    db.initialize()
    db.upsert_photo(
        PhotoRecord(
            id="photos_library:u1",
            source="photos_library",
            source_uri="u1",
            image_path=str(img),
        )
    )
    db.upsert_photo(
        PhotoRecord(
            id="local:a",
            source="local",
            source_uri=str(img),
            image_path=str(img),
            content_hash="placeholder",
        )
    )

    assert main(["dedup", "backfill-hashes", "--db", str(db_path)]) == 0
    assert "processed=2" in capsys.readouterr().out
    assert db.get_photo("photos_library:u1").content_hash is not None

    with db.connect() as conn:
        conn.execute(
            "UPDATE photos SET content_hash ="
            " (SELECT content_hash FROM photos WHERE id = 'photos_library:u1')"
            " WHERE id = 'local:a'"
        )

    assert main(["dedup", "mark", "--db", str(db_path)]) == 0
    assert "marked=1" in capsys.readouterr().out
    assert db.get_photo("local:a").duplicate_of == "photos_library:u1"


def test_cli_setup_daily_radius_propose_only(tmp_path: Path, capsys):
    db_path = tmp_path / "eddr.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()
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

    exit_code = main(["setup", "daily-radius", "--db", str(db_path), "--propose-only"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "40장" in out
    assert db.list_daily_radius_areas() == []


def test_cli_trips_recompute(tmp_path: Path, capsys):
    db_path = tmp_path / "eddr.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()
    db.replace_daily_radius_areas([("집", 37.506, 127.040, 5.0)])
    for day, hour in ((1, 10), (2, 12), (3, 18)):
        db.upsert_photo(
            PhotoRecord(
                id=f"pl:gn{day}_{hour}",
                source="photos_library",
                source_uri=f"gn{day}_{hour}",
                taken_at=f"2019-06-{day:02d}T{hour:02d}:00:00+00:00",
                latitude=37.795,
                longitude=128.918,
                indexing_status="caption_done",
            )
        )

    exit_code = main(["trips", "recompute", "--db", str(db_path)])

    assert exit_code == 0
    assert "trips_created=1" in capsys.readouterr().out
    assert db.get_photo("pl:gn2_12").trip_id == "trip_20190601_01"


def test_cli_db_normalize_taken_at(tmp_path: Path, capsys):
    db_path = tmp_path / "eddr.sqlite"
    backup = tmp_path / "backup.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()
    with db.connect() as conn:
        conn.executemany(
            "INSERT INTO photos (id, source, source_uri, taken_at) VALUES (?, ?, ?, ?)",
            [
                ("photos_library:a", "photos_library", "a", "2017-06-13T06:44:43.770000+00:00"),
                ("local:b", "local", "b", "2018-04-10T18:38:51"),
            ],
        )

    exit_code = main(["db", "normalize-taken-at", "--db", str(db_path), "--backup", str(backup)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "backup 생성" in out
    assert "remaining_without_kst=0" in out
    assert backup.exists()
    # 백업이 유효한 SQLite이고 원본과 photos 행수가 같은지 확인
    import sqlite3 as _sqlite3

    with _sqlite3.connect(backup) as bconn:
        backup_count = bconn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    with db.connect() as conn:
        orig_count = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    assert backup_count == orig_count
    # 변환: aware는 인스턴트 보존, naive는 벽시계 보존
    assert db.get_photo("photos_library:a").taken_at == "2017-06-13T15:44:43.770000+09:00"
    assert db.get_photo("local:b").taken_at == "2018-04-10T18:38:51+09:00"
    # 원본 보존
    with db.connect() as conn:
        raw = conn.execute("SELECT taken_at_raw FROM photos WHERE id = 'local:b'").fetchone()[0]
    assert raw == "2018-04-10T18:38:51"

    # 멱등 재실행: 백업 이미 존재 → 재복사 안 함, 값 불변
    exit_code = main(["db", "normalize-taken-at", "--db", str(db_path), "--backup", str(backup)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "backup 이미 존재" in out
    assert db.get_photo("photos_library:a").taken_at == "2017-06-13T15:44:43.770000+09:00"


def test_cli_geocode_backfill_country_code(tmp_path: Path, capsys, monkeypatch):
    db_path = tmp_path / "eddr.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()
    db.upsert_geocode_cache(37529, 127055, "대한민국", "서울", "강남구", None)

    from eddr.geocode.nominatim import GeocodeResult

    class _FakeClient:
        def reverse(self, lat, lng):
            return GeocodeResult(
                country="대한민국", city="서울", district="강남구", country_code="KR"
            )

    monkeypatch.setattr("eddr.geocode.nominatim.NominatimClient", lambda: _FakeClient())

    exit_code = main(["geocode", "backfill-country-code", "--db", str(db_path)])

    assert exit_code == 0
    assert "cells_updated=1" in capsys.readouterr().out
    assert db.get_geocode_cache(37529, 127055).country_code == "KR"


def test_cli_geocode_run_uses_injectable_client(tmp_path: Path, capsys, monkeypatch):
    db_path = tmp_path / "eddr.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()
    db.upsert_photo(
        PhotoRecord(
            id="photos_library:u1",
            source="photos_library",
            source_uri="u1",
            latitude=37.5,
            longitude=127.0,
        )
    )

    from eddr.geocode.nominatim import GeocodeResult

    class _FakeClient:
        def reverse(self, lat, lng):
            return GeocodeResult(country="대한민국", city="서울", district="강남구")

    monkeypatch.setattr("eddr.geocode.nominatim.NominatimClient", lambda: _FakeClient())

    # 과거 transient 실패가 잔존 — run 성공부 자동 prune이 정리해야 한다.
    db.record_error("photos_library:u1", "geocode", "old transient fail")

    exit_code = main(["geocode", "run", "--db", str(db_path)])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "photos_updated=1" in out
    assert "pruned_errors=1" in out  # u1 geocode 완료 → 잔존 에러 정리
    assert db.get_photo("photos_library:u1").country == "대한민국"


def test_cli_vision_run_accepts_food_guard_prompt(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "eddr.sqlite"
    captured = {}

    class _FakeVisionClient:
        def __init__(self, prompt_name=None, host=None):
            self.prompt_name = prompt_name
            self.host = host

    def _fake_batch(db, vector_store, vision_client, limit):
        captured["prompt_name"] = vision_client.prompt_name
        captured["limit"] = limit
        return SimpleNamespace(processed=0, failed=0)

    import eddr.vector.chroma_store as chroma_module
    import eddr.vision.batch as batch_module
    import eddr.vision.ollama_client as ollama_module

    monkeypatch.setattr(chroma_module, "ChromaVectorStore", lambda path: object())
    monkeypatch.setattr(ollama_module, "OllamaVisionClient", _FakeVisionClient)
    monkeypatch.setattr(batch_module, "run_caption_text_batch", _fake_batch)

    exit_code = main(
        [
            "vision",
            "run",
            "--db",
            str(db_path),
            "--chroma",
            str(tmp_path / "chroma"),
            "--limit",
            "0",
            "--prompt",
            "p3_hybrid_food_guard",
        ]
    )

    assert exit_code == 0
    assert captured == {"prompt_name": "p3_hybrid_food_guard", "limit": 0}


def test_cli_vision_run_prunes_resolved_index_errors(tmp_path: Path, capsys, monkeypatch):
    """vision run 성공부가 산출물 생긴 사진의 잔존 vision 에러를 자동 정리한다."""
    db_path = tmp_path / "eddr.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()
    db.upsert_photo(PhotoRecord(id="p1", source="local", source_uri="p1"))
    db.upsert_caption("p1", "gemma4:e2b", "en", "cap")  # 산출물 존재
    db.record_error("p1", "vision", "old transient fail")  # 잔존 에러

    import eddr.vector.chroma_store as chroma_module
    import eddr.vision.batch as batch_module
    import eddr.vision.ollama_client as ollama_module

    monkeypatch.setattr(chroma_module, "ChromaVectorStore", lambda path: object())
    monkeypatch.setattr(
        ollama_module, "OllamaVisionClient", lambda prompt_name=None, host=None: object()
    )
    monkeypatch.setattr(
        batch_module,
        "run_caption_text_batch",
        lambda db, vector_store, vision_client, limit: SimpleNamespace(processed=0, failed=0),
    )

    exit_code = main(["vision", "run", "--db", str(db_path), "--chroma", str(tmp_path / "chroma")])

    assert exit_code == 0
    assert "pruned_errors=1" in capsys.readouterr().out


def test_cli_vision_prompt_ab_accepts_model_and_prompt_selection(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "eddr.sqlite"
    captured = {}

    class _FakeVisionClient:
        def __init__(self, caption_model="gemma4:e2b"):
            self.caption_model = caption_model

    def _fake_prompt_ab(db, vision_client, limit, output_path, prompt_names=None, photo_ids=None):
        captured["caption_model"] = vision_client.caption_model
        captured["limit"] = limit
        captured["output_path"] = output_path
        captured["prompt_names"] = prompt_names
        captured["photo_ids"] = photo_ids
        return SimpleNamespace(processed=0, failed=0, output_path=output_path)

    import eddr.vision.ollama_client as ollama_module
    import eddr.vision.prompt_ab as prompt_ab_module

    monkeypatch.setattr(ollama_module, "OllamaVisionClient", _FakeVisionClient)
    monkeypatch.setattr(prompt_ab_module, "run_prompt_ab", _fake_prompt_ab)

    out = tmp_path / "prompt_ab.jsonl"
    exit_code = main(
        [
            "vision",
            "prompt-ab",
            "--db",
            str(db_path),
            "--limit",
            "5",
            "--caption-model",
            "qwen3-vl:8b",
            "--prompt",
            "p3_hybrid",
            "--prompt",
            "p3_hybrid_food_guard",
            "--out",
            str(out),
        ]
    )

    assert exit_code == 0
    assert captured == {
        "caption_model": "qwen3-vl:8b",
        "limit": 5,
        "output_path": out,
        "prompt_names": ("p3_hybrid", "p3_hybrid_food_guard"),
        "photo_ids": None,
    }


def test_cli_vision_prompt_ab_accepts_explicit_photo_ids(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "eddr.sqlite"
    captured = {}

    class _FakeVisionClient:
        caption_model = "fake"

        def __init__(self, caption_model="gemma4:e2b"):
            self.caption_model = caption_model

    def _fake_prompt_ab(db, vision_client, limit, output_path, prompt_names=None, photo_ids=None):
        captured["photo_ids"] = photo_ids
        return SimpleNamespace(processed=0, failed=0, output_path=output_path)

    import eddr.vision.ollama_client as ollama_module
    import eddr.vision.prompt_ab as prompt_ab_module

    monkeypatch.setattr(ollama_module, "OllamaVisionClient", _FakeVisionClient)
    monkeypatch.setattr(prompt_ab_module, "run_prompt_ab", _fake_prompt_ab)

    exit_code = main(
        [
            "vision",
            "prompt-ab",
            "--db",
            str(db_path),
            "--photo-id",
            "photos_library:48E4",
            "--photo-id",
            "photos_library:B49E",
            "--out",
            str(tmp_path / "prompt_ab.jsonl"),
        ]
    )

    assert exit_code == 0
    assert captured["photo_ids"] == ("photos_library:48E4", "photos_library:B49E")


def test_cli_vision_prompt_ab_eval_writes_summary_json(tmp_path: Path):
    prompt_ab = tmp_path / "prompt_ab.jsonl"
    prompt_ab.write_text(
        json.dumps(
            {
                "photo_id": "sprouts",
                "caption_model": "qwen3-vl:8b",
                "captions": {
                    "p3_hybrid_food_guard": (
                        "Caption: Bean sprouts in soup.\n\n"
                        "Search keywords: bean sprouts, soup, rice"
                    )
                },
                "leaks": {"p3_hybrid_food_guard": []},
                "errors": {},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps(
            {
                "sprouts": {
                    "visual_target": False,
                    "caption_claims_target": True,
                    "review_label": "wrong_object_sprouts_as_noodles",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "eval.json"

    exit_code = main(
        [
            "vision",
            "prompt-ab-eval",
            "--input",
            str(prompt_ab),
            "--labels",
            str(labels),
            "--keyword-min",
            "3",
            "--keyword-max",
            "3",
            "--forbidden-keyword",
            "noodle",
            "--positive-keyword",
            "noodle",
            "--out",
            str(out),
        ]
    )

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["summaries"] == [
        {
            "caption_model": "qwen3-vl:8b",
            "prompt_name": "p3_hybrid_food_guard",
            "rows": 1,
            "format_ok": 1,
            "privacy_ok": 1,
            "negative_rows": 1,
            "positive_rows": 0,
            "false_forbidden_keyword_hits": 0,
            "positive_keyword_hits": 0,
            "positive_recall": 1.0,
            "false_forbidden_rate": 0.0,
            "format_pass": True,
            "privacy_pass": True,
            "false_forbidden_pass": True,
            "positive_recall_pass": True,
            "passes_gates": True,
        }
    ]


def test_cli_vision_prompt_ab_eval_can_fail_on_gate_failure(tmp_path: Path):
    prompt_ab = tmp_path / "prompt_ab.jsonl"
    prompt_ab.write_text(
        json.dumps(
            {
                "photo_id": "sprouts",
                "caption_model": "gemma4:e2b",
                "captions": {
                    "p3_hybrid_food_guard": (
                        "Caption: Bean sprouts in soup.\n\n"
                        "Search keywords: bean sprouts, noodle, soup"
                    )
                },
                "leaks": {"p3_hybrid_food_guard": []},
                "errors": {},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps(
            {"sprouts": {"visual_target": False, "caption_claims_target": True}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "vision",
            "prompt-ab-eval",
            "--input",
            str(prompt_ab),
            "--labels",
            str(labels),
            "--fail-on-gate",
            "--out",
            str(tmp_path / "eval.json"),
        ]
    )

    assert exit_code == 1


def test_cli_db_prune_errors(tmp_path: Path, capsys):
    """db prune-errors가 해소된 vision 에러행만 삭제하고 개수를 출력한다."""
    db_path = tmp_path / "eddr.sqlite"
    db = EddrDatabase(db_path)
    db.initialize()
    db.upsert_photo(PhotoRecord(id="pc", source="local", source_uri="pc"))
    db.upsert_photo(PhotoRecord(id="pn", source="local", source_uri="pn"))
    db.upsert_caption("pc", "gemma4:e2b", "en", "cap")
    db.record_error("pc", "vision", "old")  # 해소 → 삭제
    db.record_error("pn", "vision", "still")  # 미해소 → 보존

    exit_code = main(["db", "prune-errors", "--db", str(db_path)])

    assert exit_code == 0
    assert "pruned 1" in capsys.readouterr().out

"""_cmd_golden CLI 핸들러 단위테스트 — 인자 파싱·러너 배선·exit code 검증.

실 DB·Chroma·Ollama 호출 없이 monkeypatch로 fake 주입한다:
- EddrDatabase, ChromaVectorStore, OllamaVisionClient, QueryExtractor: 생성자 stub
- load_golden_set: 최소 GoldenQuestion 2개 반환
- run_golden_set: 고정 GoldenRow 목록 반환
- write_report: 아무것도 안 하는 no-op
"""

from pathlib import Path

from eddr.cli import main
from eddr.query.golden import GoldenQuestion, GoldenRow

# ---------------------------------------------------------------------------
# 픽스처: 최소 골든셋 YAML
# ---------------------------------------------------------------------------

GOLDEN_YAML = """\
version: 2
questions:
  - id: G01
    question: "테스트 문항"
    match:
      photo_ids_any: ["p1"]
"""


def _make_golden_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "golden.yaml"
    p.write_text(GOLDEN_YAML, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 공통 monkeypatch 헬퍼
# ---------------------------------------------------------------------------


def _patch_deps(monkeypatch, rows: list[GoldenRow], golden_set_path: Path) -> None:
    """실 의존성 전체를 fake로 교체한다."""
    import eddr.query.golden as golden_mod
    import eddr.query.tools as tools_mod
    import eddr.vector.chroma_store as chroma_mod
    import eddr.vision.ollama_client as ollama_mod

    # DB — initialize()만 받으면 됨
    class _FakeDb:
        def __init__(self, path):
            pass

        def initialize(self):
            pass

    # ChromaVectorStore — 생성자 stub (두 번 호출: service + note_store)
    class _FakeVectorStore:
        def __init__(self, path, collection_name=None):
            pass

    # OllamaVisionClient — 생성자 stub
    class _FakeOllama:
        def __init__(self):
            pass

    # QueryService — 생성자 stub
    class _FakeService:
        def __init__(self, db, vector_store, embedding_client, note_store=None):
            pass

    # QueryExtractor — 생성자 stub
    class _FakeExtractor:
        def __init__(self, host=None):
            pass

    monkeypatch.setattr("eddr.cli.EddrDatabase", _FakeDb)
    monkeypatch.setattr(chroma_mod, "ChromaVectorStore", _FakeVectorStore)
    monkeypatch.setattr(ollama_mod, "OllamaVisionClient", _FakeOllama)
    monkeypatch.setattr(tools_mod, "QueryService", _FakeService)

    # QueryExtractor는 cli.py 내부 import — 모듈 수준 패치
    monkeypatch.setattr("eddr.query.extract.QueryExtractor", _FakeExtractor)

    # golden 로직 — 실 파이프라인 비경유
    monkeypatch.setattr(
        golden_mod,
        "load_golden_set",
        lambda path: [
            GoldenQuestion(id="G01", question="테스트 문항", match={"photo_ids_any": ["p1"]})
        ],
    )
    monkeypatch.setattr(
        golden_mod,
        "run_golden_set",
        lambda questions, search_fn, on_progress=None: rows,
    )
    monkeypatch.setattr(golden_mod, "write_report", lambda rows, path, questions=None: None)


# ---------------------------------------------------------------------------
# 테스트: 정상 경로 — exit 0 + done 출력
# ---------------------------------------------------------------------------


def test_cmd_golden_happy_path_exits_zero(tmp_path: Path, capsys, monkeypatch):
    """정상 경로: PASS 1·FAIL 0·보류 0 → exit 0, stdout에 done 포함."""
    golden_yaml = _make_golden_yaml(tmp_path)
    out_dir = tmp_path / "reports"
    out_dir.mkdir()

    rows = [
        GoldenRow(
            id="G01",
            question="테스트 문항",
            verdict="PASS",
            reasons=("photo_ids_any 충족 — p1",),
            interpretation=None,
            total=1,
            lanes=(),
            top_photos=(),
            elapsed_s=0.0,
        )
    ]

    _patch_deps(monkeypatch, rows, golden_yaml)

    exit_code = main(
        [
            "golden",
            "--db",
            str(tmp_path / "eddr.sqlite"),
            "--chroma",
            str(tmp_path / "chroma"),
            "--golden-set",
            str(golden_yaml),
            "--out",
            str(out_dir),
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "done" in out
    assert "PASS=1" in out
    assert "FAIL=0" in out


# ---------------------------------------------------------------------------
# 테스트: ConnectionError → exit 1 + 오류 메시지
# ---------------------------------------------------------------------------


def test_cmd_golden_connection_error_exits_one(tmp_path: Path, capsys, monkeypatch):
    """Ollama 연결 불가(ConnectionError) → exit 1, 안내 메시지 출력."""
    import eddr.query.golden as golden_mod
    import eddr.query.tools as tools_mod
    import eddr.vector.chroma_store as chroma_mod
    import eddr.vision.ollama_client as ollama_mod

    golden_yaml = _make_golden_yaml(tmp_path)
    out_dir = tmp_path / "reports"
    out_dir.mkdir()

    class _FakeDb:
        def __init__(self, path):
            pass

        def initialize(self):
            pass

    class _FakeVectorStore:
        def __init__(self, path, collection_name=None):
            pass

    class _FakeOllama:
        def __init__(self):
            pass

    class _FakeService:
        def __init__(self, db, vector_store, embedding_client, note_store=None):
            pass

    class _FakeExtractor:
        def __init__(self, host=None):
            pass

    monkeypatch.setattr("eddr.cli.EddrDatabase", _FakeDb)
    monkeypatch.setattr(chroma_mod, "ChromaVectorStore", _FakeVectorStore)
    monkeypatch.setattr(ollama_mod, "OllamaVisionClient", _FakeOllama)
    monkeypatch.setattr(tools_mod, "QueryService", _FakeService)
    monkeypatch.setattr("eddr.query.extract.QueryExtractor", _FakeExtractor)

    monkeypatch.setattr(
        golden_mod,
        "load_golden_set",
        lambda path: [
            GoldenQuestion(id="G01", question="테스트 문항", match={"photo_ids_any": ["p1"]})
        ],
    )
    monkeypatch.setattr(
        golden_mod,
        "run_golden_set",
        lambda questions, search_fn, on_progress=None: (_ for _ in ()).throw(
            ConnectionError("ollama down")
        ),
    )
    monkeypatch.setattr(golden_mod, "write_report", lambda rows, path, questions=None: None)

    exit_code = main(
        [
            "golden",
            "--db",
            str(tmp_path / "eddr.sqlite"),
            "--chroma",
            str(tmp_path / "chroma"),
            "--golden-set",
            str(golden_yaml),
            "--out",
            str(out_dir),
        ]
    )

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "ollama" in out

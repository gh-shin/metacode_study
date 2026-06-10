"""eddr CLI 진입점 — argparse로 db/photos/vision/search 서브커맨드를 라우팅한다."""

from __future__ import annotations

import argparse
from pathlib import Path

from eddr.db.repository import EddrDatabase


def main(argv: list[str] | None = None) -> int:
    """CLI 메인 함수 — 서브커맨드를 파싱하고 해당 핸들러를 호출한다.

    Args:
        argv: 파싱할 인수 목록. None이면 sys.argv를 사용한다.

    Returns:
        프로세스 종료 코드 (0 = 성공, 1 = 오류).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def entrypoint() -> None:
    """setuptools console_scripts 진입점 — main() 종료 코드로 프로세스를 종료한다."""
    raise SystemExit(main())


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eddr")
    subparsers = parser.add_subparsers(required=True)

    db_parser = subparsers.add_parser("db")
    db_sub = db_parser.add_subparsers(required=True)
    db_init = db_sub.add_parser("init")
    db_init.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    db_init.set_defaults(func=_cmd_db_init)

    db_load = db_sub.add_parser("load-sources")
    db_load.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    db_load.add_argument("--eda-cache", type=Path, default=Path("data/eda_cache"))
    db_load.add_argument(
        "--takeout-manifest",
        type=Path,
        default=Path("data/google_photos/manifest.jsonl"),
    )
    db_load.add_argument("--photos-export", type=Path, default=Path("data/photos_export"))
    db_load.set_defaults(func=_cmd_db_load_sources)

    photos_parser = subparsers.add_parser("photos")
    photos_sub = photos_parser.add_subparsers(required=True)
    photos_export = photos_sub.add_parser("export")
    photos_export.add_argument("--export-dir", type=Path, default=Path("data/photos_export"))
    photos_export.add_argument(
        "--export-db",
        type=Path,
        default=Path("data/photos_export/.osxphotos_export.db"),
    )
    photos_export.add_argument(
        "--report",
        type=Path,
        default=Path("data/photos_export/export.csv"),
    )
    photos_export.add_argument("--print-only", action="store_true")
    photos_export.set_defaults(func=_cmd_photos_export)

    vision_parser = subparsers.add_parser("vision")
    vision_sub = vision_parser.add_subparsers(required=True)
    vision_run = vision_sub.add_parser("run")
    vision_run.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    vision_run.add_argument("--chroma", type=Path, default=Path("data/index/chroma"))
    vision_run.add_argument("--limit", type=int, default=100)
    vision_run.add_argument(
        "--prompt",
        choices=["p3_hybrid", "p3_hybrid_v2"],
        default="p3_hybrid",
    )
    vision_run.add_argument(
        "--remote-host",
        type=str,
        default=None,
        help="2nd Ollama host (e.g. http://192.168.0.56:11434) to distribute captioning",
    )
    vision_run.set_defaults(func=_cmd_vision_run)

    vision_prompt_ab = vision_sub.add_parser("prompt-ab")
    vision_prompt_ab.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    vision_prompt_ab.add_argument("--limit", type=int, default=30)
    vision_prompt_ab.add_argument(
        "--out",
        type=Path,
        default=Path("data/eda_cache/vision_prompt_ab.jsonl"),
    )
    vision_prompt_ab.set_defaults(func=_cmd_vision_prompt_ab)

    search_parser = subparsers.add_parser("search")
    search_sub = search_parser.add_subparsers(required=True)
    search_semantic = search_sub.add_parser("semantic")
    search_semantic.add_argument("query")
    search_semantic.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    search_semantic.add_argument("--chroma", type=Path, default=Path("data/index/chroma"))
    search_semantic.add_argument("--k", type=int, default=10)
    search_semantic.set_defaults(func=_cmd_search_semantic)

    return parser


def _cmd_db_init(args: argparse.Namespace) -> int:
    """db init 서브커맨드 — SQLite DB를 초기화한다."""
    db = EddrDatabase(args.db)
    db.initialize()
    print(f"initialized {args.db}")
    return 0


def _cmd_db_load_sources(args: argparse.Namespace) -> int:
    """db load-sources 서브커맨드 — EDA 캐시·Takeout·Photos export 소스를 DB에 적재한다."""
    from eddr.db.source_loader import load_available_sources

    db = EddrDatabase(args.db)
    db.initialize()
    report = load_available_sources(
        db,
        eda_cache_dir=args.eda_cache,
        takeout_manifest=args.takeout_manifest,
        photos_export_dir=args.photos_export,
    )
    print(f"loaded={report.loaded} skipped={report.skipped} errors={report.errors}")
    return 0 if report.errors == 0 else 1


def _cmd_photos_export(args: argparse.Namespace) -> int:
    """photos export 서브커맨드 — osxphotos로 macOS Photos Library를 내보낸다."""
    from eddr.photos_export.osxphotos_export import build_export_command, run_export

    if args.print_only:
        print(" ".join(build_export_command(args.export_dir, args.export_db, args.report)))
        return 0
    run_export(args.export_dir, args.export_db, args.report)
    return 0


def _cmd_vision_run(args: argparse.Namespace) -> int:
    """vision run 서브커맨드 — Ollama 비전 모델로 사진 캡션 생성 및 임베딩 저장 배치를 실행한다."""
    from eddr.vector.chroma_store import ChromaVectorStore
    from eddr.vision.batch import run_caption_text_batch, run_caption_text_batch_dual
    from eddr.vision.ollama_client import OllamaVisionClient

    db = EddrDatabase(args.db)
    db.initialize()
    vector_store = ChromaVectorStore(args.chroma)
    local_client = OllamaVisionClient(prompt_name=args.prompt)
    if args.remote_host:
        report = run_caption_text_batch_dual(
            db=db,
            vector_store=vector_store,
            local_client=local_client,
            remote_client=OllamaVisionClient(prompt_name=args.prompt, host=args.remote_host),
            limit=args.limit,
        )
    else:
        report = run_caption_text_batch(
            db=db,
            vector_store=vector_store,
            vision_client=local_client,
            limit=args.limit,
        )
    print(f"processed={report.processed} failed={report.failed}")
    return 0 if report.failed == 0 else 1


def _cmd_vision_prompt_ab(args: argparse.Namespace) -> int:
    """vision prompt-ab 서브커맨드 — 두 프롬프트 변형의 캡션 결과를 비교 저장한다."""
    from eddr.vision.ollama_client import OllamaVisionClient
    from eddr.vision.prompt_ab import run_prompt_ab

    db = EddrDatabase(args.db)
    db.initialize()
    report = run_prompt_ab(
        db=db,
        vision_client=OllamaVisionClient(),
        limit=args.limit,
        output_path=args.out,
    )
    print(f"processed={report.processed} failed={report.failed} out={report.output_path}")
    return 0 if report.failed == 0 else 1


def _cmd_search_semantic(args: argparse.Namespace) -> int:
    """search semantic 서브커맨드 — 자연어 쿼리로 시맨틱 검색을 실행하고 결과를 출력한다."""
    from eddr.search.semantic import semantic_search
    from eddr.vector.chroma_store import ChromaVectorStore
    from eddr.vision.ollama_client import OllamaVisionClient

    results = semantic_search(
        query=args.query,
        db=EddrDatabase(args.db),
        vector_store=ChromaVectorStore(args.chroma),
        embedding_client=OllamaVisionClient(),
        k=args.k,
    )
    for result in results:
        print(f"{result.photo_id}\t{result.distance}\t{result.taken_at}\t{result.caption}")
    return 0

"""eddr CLI 진입점 — argparse로 db/photos/vision/search 서브커맨드를 라우팅한다."""

from __future__ import annotations

import argparse
from pathlib import Path

from eddr.constants import CAPTION_MODEL, DOC_RECAPTION_MODEL, NONDOC_RECAPTION_MODEL
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

    db_normalize = db_sub.add_parser("normalize-taken-at")
    db_normalize.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    db_normalize.add_argument(
        "--backup",
        type=Path,
        default=None,
        help="백필 전 DB 백업 경로 (기본: data/eddr_backup_pre_kst_<실행시각>.sqlite)",
    )
    db_normalize.set_defaults(func=_cmd_db_normalize_taken_at)

    db_prune = db_sub.add_parser("prune-errors")
    db_prune.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    db_prune.set_defaults(func=_cmd_db_prune_errors)

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

    dedup_parser = subparsers.add_parser("dedup")
    dedup_sub = dedup_parser.add_subparsers(required=True)
    dedup_backfill = dedup_sub.add_parser("backfill-hashes")
    dedup_backfill.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    dedup_backfill.add_argument("--limit", type=int, default=None)
    dedup_backfill.set_defaults(func=_cmd_dedup_backfill_hashes)

    dedup_mark = dedup_sub.add_parser("mark")
    dedup_mark.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    dedup_mark.set_defaults(func=_cmd_dedup_mark)

    geocode_parser = subparsers.add_parser("geocode")
    geocode_sub = geocode_parser.add_subparsers(required=True)
    geocode_run = geocode_sub.add_parser("run")
    geocode_run.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    geocode_run.add_argument("--limit", type=int, default=None)
    geocode_run.set_defaults(func=_cmd_geocode_run)

    geocode_backfill = geocode_sub.add_parser("backfill-country-code")
    geocode_backfill.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    geocode_backfill.set_defaults(func=_cmd_geocode_backfill_country_code)

    trips_parser = subparsers.add_parser("trips")
    trips_sub = trips_parser.add_subparsers(required=True)
    trips_recompute = trips_sub.add_parser("recompute")
    trips_recompute.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    trips_recompute.add_argument("--min-duration-hours", type=float, default=24.0)
    trips_recompute.add_argument("--max-gap-hours", type=float, default=72.0)
    trips_recompute.set_defaults(func=_cmd_trips_recompute)

    setup_parser = subparsers.add_parser("setup")
    setup_sub = setup_parser.add_subparsers(required=True)
    setup_radius = setup_sub.add_parser("daily-radius")
    setup_radius.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    setup_radius.add_argument("--top", type=int, default=8)
    setup_radius.add_argument("--min-count", type=int, default=30)
    setup_radius.add_argument("--propose-only", action="store_true")
    setup_radius.set_defaults(func=_cmd_setup_daily_radius)

    vision_parser = subparsers.add_parser("vision")
    vision_sub = vision_parser.add_subparsers(required=True)
    vision_run = vision_sub.add_parser("run")
    from eddr.vision.prompt import P3_HYBRID_PROMPT_NAME, P5_GROUNDED_PROMPT_NAME, PROMPT_NAMES

    vision_run.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    vision_run.add_argument("--chroma", type=Path, default=Path("data/index/chroma"))
    vision_run.add_argument("--limit", type=int, default=100)
    vision_run.add_argument(
        "--prompt",
        choices=PROMPT_NAMES,
        default=P3_HYBRID_PROMPT_NAME,
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
    vision_prompt_ab.add_argument("--caption-model", type=str, default=CAPTION_MODEL)
    vision_prompt_ab.add_argument("--prompt", action="append", choices=PROMPT_NAMES, default=None)
    vision_prompt_ab.add_argument("--photo-id", action="append", default=None)
    vision_prompt_ab.add_argument(
        "--out",
        type=Path,
        default=Path("data/eda_cache/vision_prompt_ab.jsonl"),
    )
    vision_prompt_ab.set_defaults(func=_cmd_vision_prompt_ab)

    vision_recaption = vision_sub.add_parser("recaption")
    vision_recaption.add_argument(
        "--photo-set",
        type=Path,
        required=True,
        help='음식 재캡션 대상 JSON {"doc": [...], "nondoc": [...]}',
    )
    vision_recaption.add_argument(
        "--doc-model", type=str, default=DOC_RECAPTION_MODEL, help="doc 그룹 캡션 모델(로컬)"
    )
    vision_recaption.add_argument(
        "--nondoc-model", type=str, default=NONDOC_RECAPTION_MODEL, help="nondoc 그룹 캡션 모델"
    )
    vision_recaption.add_argument(
        "--remote-host", type=str, default=None, help="nondoc 원격 ollama URL (없으면 로컬 사용)"
    )
    vision_recaption.add_argument("--prompt", choices=PROMPT_NAMES, default=P5_GROUNDED_PROMPT_NAME)
    vision_recaption.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    vision_recaption.add_argument("--chroma", type=Path, default=Path("data/index/chroma"))
    vision_recaption.add_argument(
        "--limit", type=int, default=None, help="검증용: doc/nondoc 각각 앞 N장만 처리"
    )
    vision_recaption.add_argument(
        "--no-vector",
        action="store_true",
        default=False,
        help="캡션만 DB 저장, Chroma 미접근 (데드락 회피 — 이후 reindex-vectors 별도 실행)",
    )
    vision_recaption.set_defaults(func=_cmd_vision_recaption)

    vision_reindex = vision_sub.add_parser("reindex-vectors")
    vision_reindex.add_argument(
        "--photo-set", type=Path, required=True, help='{"doc": [...], "nondoc": [...]} JSON 파일'
    )
    vision_reindex.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    vision_reindex.add_argument("--chroma", type=Path, default=Path("data/index/chroma"))
    vision_reindex.add_argument(
        "--embed-model",
        type=str,
        default=None,
        help="임베딩 모델 ID (기본: OllamaVisionClient 기본값)",
    )
    vision_reindex.set_defaults(func=_cmd_vision_reindex_vectors)

    vision_prompt_ab_eval = vision_sub.add_parser("prompt-ab-eval")
    vision_prompt_ab_eval.add_argument("--input", action="append", type=Path, required=True)
    vision_prompt_ab_eval.add_argument("--labels", type=Path, required=True)
    vision_prompt_ab_eval.add_argument("--forbidden-keyword", action="append", default=None)
    vision_prompt_ab_eval.add_argument("--positive-keyword", action="append", default=None)
    vision_prompt_ab_eval.add_argument("--keyword-min", type=int, default=1)
    vision_prompt_ab_eval.add_argument("--keyword-max", type=int, default=None)
    vision_prompt_ab_eval.add_argument("--positive-recall-min", type=float, default=0.9)
    vision_prompt_ab_eval.add_argument("--required-section", action="append", default=None)
    vision_prompt_ab_eval.add_argument("--fail-on-gate", action="store_true")
    vision_prompt_ab_eval.add_argument(
        "--out",
        type=Path,
        default=Path("reports/caption_audit/prompt_ab_eval.json"),
    )
    vision_prompt_ab_eval.set_defaults(func=_cmd_vision_prompt_ab_eval)

    search_parser = subparsers.add_parser("search")
    search_sub = search_parser.add_subparsers(required=True)
    search_semantic = search_sub.add_parser("semantic")
    search_semantic.add_argument("query")
    search_semantic.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    search_semantic.add_argument("--chroma", type=Path, default=Path("data/index/chroma"))
    search_semantic.add_argument("--k", type=int, default=10)
    search_semantic.set_defaults(func=_cmd_search_semantic)

    search_audit = search_sub.add_parser("audit")
    search_audit.add_argument("query")
    search_audit.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    search_audit.add_argument("--chroma", type=Path, default=Path("data/index/chroma"))
    search_audit.add_argument("--k", type=int, default=20)
    search_audit.add_argument("--keyword", action="append", default=[])
    search_audit.add_argument("--labels", type=Path, default=None)
    search_audit.add_argument(
        "--out",
        type=Path,
        default=Path("reports/caption_audit/search_audit.json"),
    )
    search_audit.set_defaults(func=_cmd_search_audit)

    serve_api_parser = subparsers.add_parser("serve-api")
    serve_api_parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="EDDR_ROOT — 상대 image_path·기본 데이터 경로의 기준 (기본: $EDDR_ROOT, 없으면 CWD)",
    )
    serve_api_parser.add_argument(
        "--db", type=Path, default=None, help="SQLite 경로 (기본: <root>/data/eddr.sqlite)"
    )
    serve_api_parser.add_argument(
        "--chroma", type=Path, default=None, help="Chroma 경로 (기본: <root>/data/index/chroma)"
    )
    serve_api_parser.add_argument(
        "--ollama-host",
        type=str,
        default=None,
        help="질의 추출기(gemma4:e2b)의 Ollama 서버 URL (기본: 로컬)",
    )
    serve_api_parser.add_argument("--host", type=str, default="127.0.0.1")
    serve_api_parser.add_argument("--port", type=int, default=8000)
    serve_api_parser.add_argument(
        "--test",
        action="store_true",
        help="기능 테스트용 baseline DB/Chroma를 생성하거나 재기동 시 복원",
    )
    serve_api_parser.set_defaults(func=_cmd_serve_api)

    golden_parser = subparsers.add_parser("golden")
    golden_parser.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    golden_parser.add_argument("--chroma", type=Path, default=Path("data/index/chroma"))
    golden_parser.add_argument(
        "--golden-set",
        type=Path,
        default=Path("docs/golden_set.yaml"),
        help="골든셋 YAML 경로 (읽기 전용 — match 규칙은 사용자가 작성)",
    )
    golden_parser.add_argument(
        "--ollama-host",
        type=str,
        default=None,
        help="질의 추출기(gemma4:e2b)의 Ollama 서버 URL (기본: 로컬)",
    )
    golden_parser.add_argument(
        "--out",
        type=Path,
        default=Path("reports/golden"),
        help="리포트 출력 디렉터리",
    )
    golden_parser.add_argument(
        "--variant",
        type=str,
        default="baseline",
        help=(
            "검색 실험 변형 목록(comma-separated): "
            "baseline,rerank_ce,rerank_flash,multiquery,hyde,full"
        ),
    )
    golden_parser.set_defaults(func=_cmd_golden)

    return parser


def _cmd_db_init(args: argparse.Namespace) -> int:
    """db init 서브커맨드 — SQLite DB를 초기화한다."""
    db = EddrDatabase(args.db)
    db.initialize()
    print(f"initialized {args.db}")
    return 0


def _cmd_db_prune_errors(args: argparse.Namespace) -> int:
    """db prune-errors 서브커맨드 — 산출물이 생긴 사진의 잔존 index_errors를 정리한다."""
    db = EddrDatabase(args.db)
    db.initialize()
    deleted = db.prune_index_errors()
    print(f"pruned {deleted} index_errors rows")
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


def _cmd_db_normalize_taken_at(args: argparse.Namespace) -> int:
    """db normalize-taken-at 서브커맨드 — taken_at을 KST로 일괄 정규화한다 (D26 M1).

    실행 전 다른 프로세스의 점유 여부를 확인하고(BEGIN IMMEDIATE), DB 파일을
    백업한 뒤(존재 시 재복사 안 함) 원본을 taken_at_raw에 스냅샷하며 정규화한다.
    """
    import sqlite3

    from eddr.db.source_loader import normalize_taken_at_backfill

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB 없음: {db_path}")
        return 1

    # 기본 백업명에 실행 시각을 박아 매 실행이 고유 백업을 남긴다 — 고정 이름은
    # 아래 'already exists' 분기에 걸려 재실행 시 백업을 건너뛰는 함정이 된다.
    if args.backup is not None:
        backup = Path(args.backup)
    else:
        from datetime import datetime

        backup = Path(f"data/eddr_backup_pre_kst_{datetime.now():%Y%m%d_%H%M%S}.sqlite")
    probe = sqlite3.connect(db_path, timeout=1.0)
    try:
        # 점유 검사 + 백업 완료까지 타 프로세스 쓰기 차단. 백업은 반드시 별도 연결로 —
        # 쓰기 트랜잭션을 쥔 연결 자신으로 backup()을 부르면 BUSY 무한 재시도로 멈춘다.
        probe.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        print(f"DB가 다른 프로세스에 점유됨(serve-api 등 종료 후 재시도): {db_path}")
        return 1
    else:
        if backup.exists():
            print(f"backup 이미 존재 — 재복사 안 함: {backup}")
        else:
            src = sqlite3.connect(db_path)
            dst = sqlite3.connect(backup)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            print(f"backup 생성: {backup}")
        probe.execute("ROLLBACK")
    finally:
        probe.close()

    db = EddrDatabase(db_path)
    db.initialize()
    report = normalize_taken_at_backfill(db)

    print(f"raw_snapshotted={report.raw_snapshotted}")
    for source in sorted(report.changed_by_source):
        day = report.calendar_day_changed_by_source.get(source, 0)
        print(f"  {source}: changed={report.changed_by_source[source]} calendar_day_changed={day}")
    print(f"remaining_without_kst={report.remaining_without_kst}")
    return 0 if report.remaining_without_kst == 0 else 1


def _cmd_dedup_backfill_hashes(args: argparse.Namespace) -> int:
    """dedup backfill-hashes 서브커맨드 — 해시 누락 사진의 BLAKE3·dHash를 채운다."""
    from eddr.dedup.pipeline import backfill_hashes

    db = EddrDatabase(args.db)
    db.initialize()
    report = backfill_hashes(db, limit=args.limit)
    print(f"processed={report.processed} dhash_failed={report.dhash_failed} errors={report.errors}")
    return 0 if report.errors == 0 else 1


def _cmd_dedup_mark(args: argparse.Namespace) -> int:
    """dedup mark 서브커맨드 — cross-source BLAKE3 동일 그룹에 duplicate_of를 마킹한다."""
    from eddr.dedup.pipeline import mark_cross_source_duplicates

    db = EddrDatabase(args.db)
    db.initialize()
    report = mark_cross_source_duplicates(db)
    print(f"groups={report.groups} marked={report.marked}")
    return 0


def _cmd_geocode_run(args: argparse.Namespace) -> int:
    """geocode run 서브커맨드 — Nominatim reverse geocoding으로 행정구역 필드를 채운다."""
    import eddr.geocode.nominatim as nominatim
    from eddr.geocode.pipeline import geocode_photos

    db = EddrDatabase(args.db)
    db.initialize()
    report = geocode_photos(db, nominatim.NominatimClient(), limit=args.limit)
    pruned = db.prune_index_errors()
    print(
        f"photos_updated={report.photos_updated} cells_fetched={report.cells_fetched}"
        f" cache_hits={report.cache_hits} errors={report.errors} aborted={report.aborted}"
        f" pruned_errors={pruned}"
    )
    return 0 if not report.aborted and report.errors == 0 else 1


def _cmd_geocode_backfill_country_code(args: argparse.Namespace) -> int:
    """geocode backfill-country-code 서브커맨드 — 캐시 셀의 ISO country_code를 채운다."""
    import eddr.geocode.nominatim as nominatim
    from eddr.geocode.pipeline import backfill_country_codes

    db = EddrDatabase(args.db)
    db.initialize()
    report = backfill_country_codes(db, nominatim.NominatimClient())
    print(f"cells_updated={report.cells_updated} errors={report.errors} aborted={report.aborted}")
    return 0 if not report.aborted and report.errors == 0 else 1


def _cmd_trips_recompute(args: argparse.Namespace) -> int:
    """trips recompute 서브커맨드 — Daily Radius 밖 24h+ 세그먼트로 trip을 전체 재계산한다."""
    from eddr.trips.pipeline import recompute_trips

    db = EddrDatabase(args.db)
    db.initialize()
    report = recompute_trips(
        db,
        min_duration_hours=args.min_duration_hours,
        max_gap_hours=args.max_gap_hours,
    )
    print(f"trips_created={report.trips_created} photos_assigned={report.photos_assigned}")
    return 0


def _cmd_setup_daily_radius(args: argparse.Namespace) -> int:
    """setup daily-radius 서브커맨드 — 밀도 후보를 제안하고 wizard로 사용자 확정을 받는다."""
    from eddr.daily_radius.wizard import format_candidate, propose_candidates, run_wizard

    db = EddrDatabase(args.db)
    db.initialize()
    candidates = propose_candidates(db, top_n=args.top, min_count=args.min_count)
    if not candidates:
        print("후보 없음 — GPS 사진이 부족하거나 --min-count가 너무 높습니다.")
        return 0
    if args.propose_only:
        for index, candidate in enumerate(candidates, start=1):
            print(format_candidate(index, len(candidates), candidate))
        return 0
    saved = run_wizard(db, candidates)
    print(f"saved={saved}")
    return 0


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
    pruned = db.prune_index_errors()
    print(f"processed={report.processed} failed={report.failed} pruned_errors={pruned}")
    return 0 if report.failed == 0 else 1


def _cmd_vision_recaption(args: argparse.Namespace) -> int:
    """vision recaption 서브커맨드 — 투트랙 라우팅으로 음식 사진 재캡션을 실행한다.

    doc 그룹은 로컬 OCR 우위 모델, nondoc 그룹은 원격(또는 로컬) gemma4 모델로 캡션한다.
    """
    import json

    from eddr.vector.chroma_store import ChromaVectorStore
    from eddr.vision.batch import run_caption_text_batch_routed_dual
    from eddr.vision.ollama_client import OllamaVisionClient

    foodset = json.loads(args.photo_set.read_text(encoding="utf-8"))

    db = EddrDatabase(args.db)
    db.initialize()

    def _resolve_photos(entries: list[dict]) -> list:
        photos = []
        for entry in entries:
            pid = entry["photo_id"]
            photo = db.get_photo(pid)
            if photo is None:
                print(f"경고: photo_id '{pid}' DB에 없음 — skip")
                continue
            photos.append(photo)
        return photos

    doc_entries = foodset.get("doc", [])
    nondoc_entries = foodset.get("nondoc", [])
    if args.limit is not None:
        doc_entries = doc_entries[: args.limit]
        nondoc_entries = nondoc_entries[: args.limit]

    doc_photos = _resolve_photos(doc_entries)
    nondoc_photos = _resolve_photos(nondoc_entries)

    vector_store = ChromaVectorStore(args.chroma)
    doc_client = OllamaVisionClient(caption_model=args.doc_model, prompt_name=args.prompt)
    nondoc_local_client = OllamaVisionClient(
        caption_model=args.nondoc_model, prompt_name=args.prompt
    )
    nondoc_remote_client = (
        OllamaVisionClient(
            caption_model=args.nondoc_model, prompt_name=args.prompt, host=args.remote_host
        )
        if args.remote_host
        else nondoc_local_client
    )

    report = run_caption_text_batch_routed_dual(
        db,
        vector_store,
        doc_client,  # embed_client = doc_client (로컬, embedding_model 기본값 사용)
        doc_client=doc_client,
        nondoc_local_client=nondoc_local_client,
        nondoc_remote_client=nondoc_remote_client,
        doc_photos=doc_photos,
        nondoc_photos=nondoc_photos,
        persist_vector=not args.no_vector,
    )
    pruned = db.prune_index_errors()
    print(f"processed={report.processed} failed={report.failed} pruned_errors={pruned}")
    return 0 if report.failed == 0 else 1


def _cmd_vision_reindex_vectors(args: argparse.Namespace) -> int:
    """vision reindex-vectors 서브커맨드 — 단일 스레드로 Chroma 벡터 색인을 재구축한다.

    photo-set JSON의 doc·nondoc photo_id에 대해 DB에서 최신 캡션을 읽고
    임베딩·Chroma upsert·embedding_record를 순차 실행한다. 워커 스레드 없음.
    """
    import json

    from eddr.vector.chroma_store import ChromaVectorStore
    from eddr.vision.ollama_client import OllamaVisionClient

    photo_set = json.loads(args.photo_set.read_text(encoding="utf-8"))
    all_entries = photo_set.get("doc", []) + photo_set.get("nondoc", [])

    db = EddrDatabase(args.db)
    db.initialize()
    vector_store = ChromaVectorStore(args.chroma)

    embed_kwargs: dict = {}
    if args.embed_model:
        embed_kwargs["embedding_model"] = args.embed_model
    embed_client = OllamaVisionClient(**embed_kwargs)

    indexed = skipped = 0
    for i, entry in enumerate(all_entries, 1):
        photo_id = entry["photo_id"]
        text = db.get_latest_caption(photo_id)
        if text is None:
            skipped += 1
            continue
        embedding = embed_client.embed_texts([text])[0]
        vector_id = f"caption_text:{photo_id}:{embed_client.embedding_model}"
        photo = db.get_photo(photo_id)
        source = photo.source if photo else "unknown"
        vector_store.upsert(
            ids=[vector_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[
                {
                    "photo_id": photo_id,
                    "source": source,
                    "kind": "caption_text",
                    "model_id": embed_client.embedding_model,
                }
            ],
        )
        db.upsert_embedding_record(
            photo_id=photo_id,
            kind="caption_text",
            model_id=embed_client.embedding_model,
            vector_id=vector_id,
            dimensions=len(embedding),
        )
        indexed += 1
        if i % 20 == 0:
            print(f"[{i}/{len(all_entries)}] indexed={indexed} skipped={skipped}")

    print(f"완료: indexed={indexed} skipped={skipped}")
    return 0


def _cmd_vision_prompt_ab(args: argparse.Namespace) -> int:
    """vision prompt-ab 서브커맨드 — 두 프롬프트 변형의 캡션 결과를 비교 저장한다."""
    from eddr.vision.ollama_client import OllamaVisionClient
    from eddr.vision.prompt_ab import run_prompt_ab

    db = EddrDatabase(args.db)
    db.initialize()
    report = run_prompt_ab(
        db=db,
        vision_client=OllamaVisionClient(caption_model=args.caption_model),
        limit=args.limit,
        output_path=args.out,
        prompt_names=tuple(args.prompt) if args.prompt else None,
        photo_ids=tuple(args.photo_id) if args.photo_id else None,
    )
    print(f"processed={report.processed} failed={report.failed} out={report.output_path}")
    return 0 if report.failed == 0 else 1


def _cmd_vision_prompt_ab_eval(args: argparse.Namespace) -> int:
    """vision prompt-ab-eval 서브커맨드 — prompt-ab JSONL을 라벨셋으로 채점한다."""
    import json
    from dataclasses import asdict

    from eddr.query.audit import load_caption_audit_labels
    from eddr.vision.prompt_ab_eval import (
        DEFAULT_FORBIDDEN_KEYWORDS,
        DEFAULT_POSITIVE_KEYWORDS,
        evaluate_prompt_ab_outputs,
    )

    report = evaluate_prompt_ab_outputs(
        paths=args.input,
        labels=load_caption_audit_labels(args.labels),
        forbidden_keywords=tuple(args.forbidden_keyword or DEFAULT_FORBIDDEN_KEYWORDS),
        positive_keywords=tuple(args.positive_keyword or DEFAULT_POSITIVE_KEYWORDS),
        keyword_min=args.keyword_min,
        keyword_max=args.keyword_max,
        positive_recall_min=args.positive_recall_min,
        required_sections=tuple(args.required_section or ()),
    )
    payload = {
        "summaries": [
            asdict(summary)
            for _, summary in sorted(report.summaries.items(), key=lambda item: item[0])
        ],
        "rows": [asdict(row) for row in report.rows],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    if args.fail_on_gate and any(not summary.passes_gates for summary in report.summaries.values()):
        return 1
    return 0


def _cmd_serve_api(args: argparse.Namespace) -> int:
    """serve-api 서브커맨드 — FastAPI 웹 API 서버를 기동한다 (ADR-0008)."""
    import os

    from eddr.server.app import serve_api
    from eddr.server.deps import ServerConfig

    root = (args.root or Path(os.environ.get("EDDR_ROOT") or Path.cwd())).resolve()
    config = ServerConfig(
        root=root,
        db_path=args.db or root / "data" / "eddr.sqlite",
        chroma_path=args.chroma or root / "data" / "index" / "chroma",
        ollama_host=args.ollama_host,
    )
    if args.test and not _prepare_test_baseline(config.db_path, config.chroma_path, root):
        return 1
    serve_api(config, host=args.host, port=args.port)
    return 0


def _prepare_test_baseline(db_path: Path, chroma_path: Path, root: Path) -> bool:
    """serve-api --test용 baseline을 없으면 만들고, 있으면 현재 데이터에 복원한다."""
    import shutil

    baseline_dir = root / "data" / "test-baseline"
    baseline_db = baseline_dir / "eddr.sqlite"
    baseline_chroma = baseline_dir / "chroma"
    if not baseline_db.exists():
        if not db_path.exists():
            print(f"test baseline 생성 실패: DB 없음: {db_path}")
            return False
        baseline_dir.mkdir(parents=True, exist_ok=True)
        _sqlite_backup(db_path, baseline_db)
        if chroma_path.exists():
            if baseline_chroma.exists():
                shutil.rmtree(baseline_chroma)
            shutil.copytree(chroma_path, baseline_chroma)
        print(f"test baseline 생성: {baseline_dir}")
        return True
    _sqlite_backup(baseline_db, db_path)
    if baseline_chroma.exists():
        if chroma_path.exists():
            shutil.rmtree(chroma_path)
        shutil.copytree(baseline_chroma, chroma_path)
    elif chroma_path.exists():
        shutil.rmtree(chroma_path)
    print(f"test baseline 복원: {baseline_dir}")
    return True


def _sqlite_backup(source: Path, target: Path) -> None:
    """SQLite backup API로 source DB를 target DB에 복사한다."""
    import sqlite3

    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _cmd_golden(args: argparse.Namespace) -> int:
    """golden 서브커맨드 — 골든셋 v2 자동 채점 (검색 파이프라인 직접 호출, ⑧ 재정의).

    문항마다 라우트 코어와 동일한 ``run_search``(추출→trip 스코프→RRF 검색→KST
    그룹핑)를 HTTP 비경유로 실행하고 match 규칙으로 PASS/FAIL/보류를 판정한다.
    """
    from datetime import datetime

    from eddr.query.expansion import build_query_expander
    from eddr.query.extract import QueryExtractor
    from eddr.query.golden import (
        load_golden_set,
        run_golden_set,
        write_report,
        write_variant_matrix,
    )
    from eddr.query.notes_bm25 import NotesBM25Index
    from eddr.query.rerankers import build_reranker
    from eddr.query.retrieval_config import get_retrieval_config
    from eddr.query.tools import QueryService
    from eddr.server.deps import NOTE_COLLECTION
    from eddr.server.routes.search import run_search
    from eddr.vector.chroma_store import ChromaVectorStore
    from eddr.vision.ollama_client import OllamaVisionClient

    db = EddrDatabase(args.db)
    db.initialize()
    extractor = QueryExtractor(host=args.ollama_host)

    questions = load_golden_set(args.golden_set)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    variant_names = [name.strip() for name in args.variant.split(",") if name.strip()]
    if not variant_names:
        variant_names = ["baseline"]
    print(f"golden v2: {len(questions)}문항 · 검색 파이프라인 직접 호출", flush=True)
    rows_by_variant = {}
    try:
        for variant_name in variant_names:
            config = get_retrieval_config(variant_name)
            service = QueryService(
                db,
                vector_store=ChromaVectorStore(args.chroma),
                embedding_client=OllamaVisionClient(),
                reranker=build_reranker(config.rerank),
                query_expander=build_query_expander(
                    config.expansion, ollama_host=args.ollama_host
                ),
                # note leg 포함 — serve-api 검색 경로와 동형으로 채점한다 (D26 M5 회귀 게이트).
                note_store=ChromaVectorStore(args.chroma, collection_name=NOTE_COLLECTION),
                notes_bm25=NotesBM25Index.from_db(db),
            )
            rows_by_variant[variant_name] = run_golden_set(
                questions,
                lambda query, service=service: run_search(extractor, service, query),
                on_progress=lambda line, variant=variant_name: print(
                    f"[{variant}] {line}", flush=True
                ),
            )
    except ConnectionError:
        print("ollama 연결 불가 — ollama serve 후 다시 시도하세요.", flush=True)
        return 1
    if variant_names == ["baseline"]:
        rows = rows_by_variant["baseline"]
        report_path = args.out / f"{stamp}_v2_search.md"
        write_report(rows, report_path, questions=questions)
    else:
        report_path = args.out / f"{stamp}_variant_matrix.md"
        write_variant_matrix(rows_by_variant, report_path)
        rows = rows_by_variant[variant_names[0]]
    passed = sum(1 for row in rows if row.verdict == "PASS")
    failed = sum(1 for row in rows if row.verdict == "FAIL")
    held = sum(1 for row in rows if row.verdict == "보류")
    print(f"done PASS={passed} FAIL={failed} 보류={held} report={report_path}", flush=True)
    return 0


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


def _cmd_search_audit(args: argparse.Namespace) -> int:
    """search audit 서브커맨드 — 검색 top-k provenance를 JSON으로 저장한다."""
    import json
    from dataclasses import asdict

    from eddr.query.audit import load_caption_audit_labels, trace_caption_search
    from eddr.vector.chroma_store import ChromaVectorStore
    from eddr.vision.ollama_client import OllamaVisionClient

    db = EddrDatabase(args.db)
    db.initialize()
    report = trace_caption_search(
        db=db,
        vector_store=ChromaVectorStore(args.chroma),
        embedding_client=OllamaVisionClient(),
        query=args.query,
        keywords=args.keyword,
        k=args.k,
        labels=load_caption_audit_labels(args.labels) if args.labels else None,
    )
    payload = asdict(report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0

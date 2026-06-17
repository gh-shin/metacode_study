"""retrieval 마이크로벤치 — 검색 레이어만 분리해 recall을 측정한다 (LLM 무관).

골든셋 작성(2026-06-11) 때 실DB에서 뽑은 ground truth 모집단을 SQL로 재현하고,
두 층을 측정한다:

1. **production recall@k** — `QueryService.semantic_search_photos`를 실제 서비스
   경로 그대로 호출(over-fetch → SQL 필터 → 절단)한 최종 결과의 GT 적중.
2. **진단 rank 분포** — 같은 질의 임베딩으로 Chroma 전역 상위 N(기본 2000)을 받아
   GT가 임베딩 순위 어디에 있는지(recall@100/500/2000) 본다. 파이프라인 설정과
   무관한 임베딩 leg 자체의 품질 신호로, "over-fetch를 키우면 잡히는가 vs
   임베딩이 아예 못 찾는가"를 가른다.

주의: GT는 캡션 LIKE 기반 proxy라 절대값이 아닌 **설정 간 상대 비교**용이다.
특히 lexical leg(FTS)를 평가할 때는 GT 정의와 순환하므로 E2E 골든셋으로 보완한다.

실행 (repo 루트):
    uv run python scripts/bench_retrieval.py --label baseline
    uv run python scripts/bench_retrieval.py --gt-only   # GT 카운트 검증만
결과는 reports/rag_quality/retrieval/experiments.jsonl에 누적되고 RESULTS.md가 재생성된다.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from eddr.db.repository import EddrDatabase
from eddr.query.tools import QUERY_EMBED_INSTRUCTION, QueryService
from eddr.vector.chroma_store import ChromaVectorStore
from eddr.vision.ollama_client import OllamaVisionClient

DIAG_K = 2000
DIAG_CUTS = (100, 500, 2000)
EXPOSED = "p.duplicate_of IS NULL AND p.indexing_status != 'skipped_video'"
DEFAULT_GT_CAPTION_MODEL = "gemma4:e2b"
ALL_GT_CAPTION_MODELS = "all"


@dataclass(frozen=True)
class GtSpec:
    """GT 모집단 정의 — 골든셋 reference와 동일한 추출 조건.

    Attributes:
        caption_terms: 캡션 LIKE OR 조건 (영어, 부분 일치).
        trip_ids: trip 한정.
        extra_sql: photos 별칭 p에 대한 추가 WHERE 조각 (장소 등).
        extra_params: extra_sql 바인딩 파라미터.
        path_terms: image_path NFC 정규화 후 부분 일치 (한글 경로 — python 측).
        expected: 골든셋 reference 카운트. 불일치 시 시작 단계에서 실패한다.
    """

    expected: int
    caption_terms: tuple[str, ...] = ()
    trip_ids: tuple[str, ...] = ()
    extra_sql: str = ""
    extra_params: tuple[str, ...] = ()
    path_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchQuestion:
    """벤치 1문항 — production 호출 입력과 GT 정의.

    keywords는 --rrf 시 전달되는 영어 lexical 키워드 — GT 추출 용어와 겹치는
    문항은 순환 편향(인플레)이 있으므로 절대값이 아닌 회귀 감시용으로 본다.
    """

    qid: str
    query: str
    gt: GtSpec
    filters: dict = field(default_factory=dict)
    keywords: tuple[str, ...] = ()


BENCH: tuple[BenchQuestion, ...] = (
    BenchQuestion(
        qid="G01",
        query="돌로미티 산악 풍경",
        filters={"countries": ["이탈리아"]},
        keywords=("mountain", "peak"),
        gt=GtSpec(
            expected=104,
            trip_ids=("trip_20190629_01",),
            caption_terms=("mountain", "alpine", "peak"),
        ),
    ),
    BenchQuestion(
        qid="G02",
        query="도로와 차량 이동",
        filters={"countries": ["아이슬란드"]},
        keywords=("road", "car"),
        gt=GtSpec(
            expected=130,
            trip_ids=("trip_20210218_01", "trip_20220917_01", "trip_20250924_01"),
            # 골든셋 작성 시 원본 패턴 — ' car '·'van '은 card/carved 류 과대매칭 방지.
            caption_terms=("road", " car ", "vehicle", "van ", "driving"),
        ),
    ),
    BenchQuestion(
        qid="G03",
        query="밤하늘 은하수와 별",
        # Stage 2(2026-06-11)부터 trip_id 경로 — countries=["몽골"]은 geocode 기반이라
        # GT 19장 중 3장만 통과(GPS 무 16장 탈락)하는 구조적 천장이었다. 이전 run들의
        # G03 열은 countries 기준 측정값.
        filters={"trip_id": "trip_20180713_01"},
        keywords=("milky way", "stars"),
        gt=GtSpec(
            expected=19,
            trip_ids=("trip_20180713_01",),
            caption_terms=("milky way", "starry", "night sky", "stars"),
        ),
    ),
    BenchQuestion(
        qid="G05",
        query="겹벚꽃 봄꽃 클로즈업",
        keywords=("cherry blossom", "flower"),
        gt=GtSpec(
            expected=21,
            caption_terms=("blossom", "flower", "cherry"),
            path_terms=("20190501_철산", "20190505_개심사"),
        ),
    ),
    BenchQuestion(
        qid="G06",
        query="한국 전통 사찰 건물과 꽃",
        keywords=("temple",),
        gt=GtSpec(expected=16, path_terms=("개심사",)),
    ),
    BenchQuestion(
        qid="G07",
        query="검은 현무암 바위 해안",
        filters={"cities": ["제주", "서귀포"]},
        keywords=("basalt", "black rock"),
        gt=GtSpec(
            expected=82,
            caption_terms=("volcanic", "basalt", "black rock", "rocky"),
            extra_sql=(
                "(p.city LIKE '%제주%' OR p.city LIKE '%서귀포%'"
                " OR p.district LIKE '%제주%' OR p.district LIKE '%서귀포%')"
            ),
        ),
    ),
    BenchQuestion(
        qid="G09",
        query="음식 식사 메뉴",
        filters={"cities": ["용산"]},
        keywords=("food", "meal"),
        # 골든셋 reference의 115는 '%eat%' substring(great·seat 등) 과대매칭 + 노출
        # 불변식 미적용 수치 — 정확한 노출 모집단은 27장이다 (2026-06-11 재검증).
        gt=GtSpec(
            expected=27,
            caption_terms=("food", "meal", "restaurant", "dish"),
            extra_sql="p.district = '용산구'",
        ),
    ),
    BenchQuestion(
        qid="G10",
        query="은하수",
        keywords=("milky way",),
        gt=GtSpec(expected=36, caption_terms=("milky way",)),
    ),
)


def resolve_gt(
    db_path: Path, spec: GtSpec, gt_caption_model: str = DEFAULT_GT_CAPTION_MODEL
) -> set[str]:
    """GtSpec을 실DB에 적용해 GT photo_id 집합을 반환한다."""
    clauses = [EXPOSED]
    params: list[str] = []
    if spec.caption_terms:
        ors = " OR ".join("c.text LIKE '%' || ? || '%'" for _ in spec.caption_terms)
        caption_clauses = ["c.photo_id = p.id"]
        if gt_caption_model != ALL_GT_CAPTION_MODELS:
            caption_clauses.append("c.model_id = ?")
            params.append(gt_caption_model)
        caption_clauses.append(f"({ors})")
        clauses.append(
            f"EXISTS (SELECT 1 FROM captions c WHERE {' AND '.join(caption_clauses)})"
        )
        params.extend(spec.caption_terms)
    if spec.trip_ids:
        placeholders = ",".join("?" * len(spec.trip_ids))
        clauses.append(f"p.trip_id IN ({placeholders})")
        params.extend(spec.trip_ids)
    if spec.extra_sql:
        clauses.append(spec.extra_sql)
        params.extend(spec.extra_params)
    sql = f"SELECT p.id, p.image_path FROM photos p WHERE {' AND '.join(clauses)}"
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    if not spec.path_terms:
        return {row[0] for row in rows}
    # 한글 폴더명은 NFD로 저장돼 NFC 리터럴과 SQL LIKE가 불일치 — python 측에서 정규화 매칭.
    ids: set[str] = set()
    for photo_id, image_path in rows:
        normalized = unicodedata.normalize("NFC", image_path or "")
        if any(term in normalized for term in spec.path_terms):
            ids.add(photo_id)
    return ids


def check_gt(
    db_path: Path, gt_caption_model: str = DEFAULT_GT_CAPTION_MODEL
) -> dict[str, set[str]]:
    """전 문항 GT를 추출하고 골든셋 reference 카운트와 대조한다."""
    gt_by_qid: dict[str, set[str]] = {}
    mismatches: list[str] = []
    for question in BENCH:
        ids = resolve_gt(db_path, question.gt, gt_caption_model=gt_caption_model)
        gt_by_qid[question.qid] = ids
        status = "ok" if len(ids) == question.gt.expected else "MISMATCH"
        print(
            f"  GT {question.qid}: {len(ids)} (expected {question.gt.expected}) {status}",
            flush=True,
        )
        if len(ids) != question.gt.expected:
            mismatches.append(question.qid)
    if mismatches:
        raise SystemExit(f"GT count mismatch: {mismatches} — 추출 조건이 골든셋과 다름")
    return gt_by_qid


def _load_cross_encoder():
    """bge-reranker-v2-m3 cross-encoder를 지연 로드한다 (--rerank 전용, ad-hoc 의존성)."""
    from sentence_transformers import CrossEncoder

    class _CrossEncoderReranker:
        def __init__(self):
            self.model = CrossEncoder("BAAI/bge-reranker-v2-m3")

        def score(self, query: str, captions: list[str]) -> list[float]:
            pairs = [(query, caption) for caption in captions]
            return [float(s) for s in self.model.predict(pairs)]

    return _CrossEncoderReranker()


def run_bench(args: argparse.Namespace) -> None:
    gt_by_qid = check_gt(args.db, gt_caption_model=args.gt_caption_model)
    if args.gt_only:
        print("GT check passed — 측정은 생략(--gt-only).", flush=True)
        return

    # 미지정=production 기본(QueryService 기본 instruction), 'none'=미적용, 그 외=커스텀.
    template = None if args.instruct == "none" else args.instruct or QUERY_EMBED_INSTRUCTION
    embed_client = OllamaVisionClient(host=args.ollama_host)
    vector_store = ChromaVectorStore(args.chroma)
    db = EddrDatabase(args.db)
    db.initialize()  # captions_fts 마이그레이션 포함 (멱등)
    reranker = _load_cross_encoder() if args.rerank else None
    service = QueryService(
        db,
        vector_store=vector_store,
        embedding_client=embed_client,
        query_embed_template=template,
        reranker=reranker,
    )
    diag_k = min(DIAG_K, vector_store.count())

    rows = []
    for question in BENCH:
        gt = gt_by_qid[question.qid]
        started = time.perf_counter()
        call_kwargs = dict(question.filters)
        if args.rrf and question.keywords:
            call_kwargs["keywords"] = list(question.keywords)
        results = service.semantic_search_photos(query=question.query, k=args.k, **call_kwargs)
        latency = time.perf_counter() - started
        returned = [r.photo_id for r in results]
        hits = len(set(returned) & gt)

        diag_text = template.format(query=question.query) if template else question.query
        embedding = embed_client.embed_texts([diag_text])[0]
        ranked: list[str] = []
        seen: set[str] = set()
        for hit in vector_store.query(embedding=embedding, k=diag_k):
            if hit.photo_id and hit.photo_id not in seen:
                seen.add(hit.photo_id)
                ranked.append(hit.photo_id)
        diag = {
            f"diag_recall@{cut}": round(len(set(ranked[:cut]) & gt) / len(gt), 3)
            for cut in DIAG_CUTS
        }
        row = {
            "qid": question.qid,
            "gt_size": len(gt),
            "returned": len(returned),
            "hits": hits,
            "recall@k": round(hits / len(gt), 3),
            # k-정규화 — GT가 k보다 클 때 달성 가능 상한(min(k, GT)) 대비 적중률.
            "recall_norm": round(hits / min(args.k, len(gt)), 3),
            "precision": round(hits / len(returned), 3) if returned else None,
            "latency_s": round(latency, 2),
            **diag,
        }
        rows.append(row)
        print(
            f"  {question.qid}: returned {row['returned']}/{args.k}, hits {hits}, "
            f"norm {row['recall_norm']}, diag@500 {row['diag_recall@500']}",
            flush=True,
        )

    n = len(rows)
    record = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "git_rev": _git_rev(),
        "label": args.label,
        "config": {
            "k": args.k,
            "embed_model": "qwen3-embedding:8b",
            "instruct": template,
            "rrf": bool(args.rrf),
            "rerank": bool(args.rerank),
            "gt_caption_model": args.gt_caption_model,
        },
        "questions": rows,
        "aggregate": {
            "mean_recall@k": round(sum(r["recall@k"] for r in rows) / n, 3),
            "mean_recall_norm": round(sum(r["recall_norm"] for r in rows) / n, 3),
            "mean_diag_recall@500": round(sum(r["diag_recall@500"] for r in rows) / n, 3),
            "mean_returned": round(sum(r["returned"] for r in rows) / n, 1),
            "total_latency_s": round(sum(r["latency_s"] for r in rows), 1),
        },
    }
    args.out.mkdir(parents=True, exist_ok=True)
    jsonl_path = args.out / "experiments.jsonl"
    with jsonl_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    write_results_md(jsonl_path, args.out / "RESULTS.md")
    print(
        f"\nlabel={args.label}  mean recall@{args.k}={record['aggregate']['mean_recall@k']}  "
        f"mean diag@500={record['aggregate']['mean_diag_recall@500']}",
        flush=True,
    )
    print(f"appended → {jsonl_path}", flush=True)


def write_results_md(jsonl_path: Path, md_path: Path) -> None:
    """experiments.jsonl 전체를 비교 테이블로 재생성한다 — 실험 결과의 단일 저장소."""
    records = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    qids = [q.qid for q in BENCH]
    lines = [
        "# retrieval 마이크로벤치 결과",
        "",
        "골든셋 ground truth(proxy, 캡션 LIKE 기반) 대비 검색 레이어 단독 측정.",
        "절대값이 아니라 **설정 간 상대 비교**용이다. 생성: scripts/bench_retrieval.py.",
        "",
        "## run 비교 — k-정규화 recall (적중 / 달성가능 상한 min(k, GT))",
        "",
        "| label | ts | git | k | GT model | " + " | ".join(qids) + " | mean |",
        "|---|---|---|---|---|" + "---|" * (len(qids) + 1),
    ]
    for rec in records:
        k_cfg = rec["config"]["k"]
        by_qid = {r["qid"]: r for r in rec["questions"]}
        cells = []
        norms = []
        for q in qids:
            if q not in by_qid:
                cells.append("—")
                continue
            r = by_qid[q]
            cap = min(k_cfg, r["gt_size"])
            norm = r.get("recall_norm", round(r["hits"] / cap, 3))
            norms.append(norm)
            cells.append(f"{norm} ({r['hits']}/{cap})")
        mean_norm = rec["aggregate"].get(
            "mean_recall_norm", round(sum(norms) / len(norms), 3) if norms else 0
        )
        lines.append(
            f"| {rec['label']} | {rec['ts'][5:16]} | {rec['git_rev']} | {rec['config']['k']} "
            f"| {rec['config'].get('gt_caption_model', 'legacy')} | "
            + " | ".join(cells)
            + f" | **{mean_norm}** |"
        )
    lines += [
        "",
        "## run 비교 — 진단 recall@500 (임베딩 leg 전역 순위, 필터·절단 무관)",
        "",
        "| label | GT model | " + " | ".join(qids) + " | mean |",
        "|---|---|" + "---|" * (len(qids) + 1),
    ]
    for rec in records:
        by_qid = {r["qid"]: r for r in rec["questions"]}
        cells = [str(by_qid[q]["diag_recall@500"]) if q in by_qid else "—" for q in qids]
        lines.append(
            f"| {rec['label']} | {rec['config'].get('gt_caption_model', 'legacy')} | "
            + " | ".join(cells)
            + f" | **{rec['aggregate']['mean_diag_recall@500']}** |"
        )
    latest = records[-1]
    lines += [
        "",
        (
            f"## 최신 run 상세 — {latest['label']} ({latest['ts']}, "
            f"GT model {latest['config'].get('gt_caption_model', 'legacy')})"
        ),
        "",
        "| qid | GT | returned | hits | norm | recall@k | precision | diag@100 | diag@500 "
        "| diag@2000 | latency |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    latest_k = latest["config"]["k"]
    for r in latest["questions"]:
        norm = r.get("recall_norm", round(r["hits"] / min(latest_k, r["gt_size"]), 3))
        lines.append(
            f"| {r['qid']} | {r['gt_size']} | {r['returned']} | {r['hits']} | {norm} "
            f"| {r['recall@k']} | {r['precision']} | {r['diag_recall@100']} "
            f"| {r['diag_recall@500']} | {r['diag_recall@2000']} | {r['latency_s']}s |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _git_rev() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="retrieval 마이크로벤치")
    parser.add_argument("--db", type=Path, default=Path("data/eddr.sqlite"))
    parser.add_argument("--chroma", type=Path, default=Path("data/index/chroma"))
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("reports/rag_quality/retrieval"),
        help="결과 출력 디렉터리 (기본: reports/rag_quality/retrieval)",
    )
    parser.add_argument("--label", default=None, help="실험 이름 (experiments.jsonl 기록)")
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument(
        "--instruct",
        default=None,
        help="질의 instruction 템플릿({query} 치환). 미지정=production 기본, 'none'=미적용",
    )
    parser.add_argument("--ollama-host", default=None)
    parser.add_argument(
        "--rrf", action="store_true", help="문항별 영어 keywords를 전달해 BM25 RRF 융합 측정"
    )
    parser.add_argument(
        "--rerank", action="store_true", help="bge-reranker-v2-m3 cross-encoder 재정렬 측정"
    )
    parser.add_argument("--gt-only", action="store_true", help="GT 카운트 검증만 수행")
    parser.add_argument(
        "--gt-caption-model",
        default=DEFAULT_GT_CAPTION_MODEL,
        help=(
            "GT 캡션 LIKE 추출에 사용할 caption model_id. "
            "'all'=모든 caption model 포함(진단용, expected count 검증은 그대로 적용)"
        ),
    )
    args = parser.parse_args()
    if not args.gt_only and not args.label:
        parser.error("--label은 측정 run에 필수 (예: --label baseline)")
    run_bench(args)


if __name__ == "__main__":
    main()

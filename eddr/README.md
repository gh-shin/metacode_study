# EDDR

EDDR is a local personal photo-memory database and retrieval project.

Current build scope: foundation SQLite ledger, Chroma caption-text vector sidecar,
Photos export wrapper, Vision caption batch, and semantic search CLI.

## Quick Start

Install dependencies:

```bash
uv sync
```

Initialize and load available source metadata:

```bash
uv run eddr db init --db data/eddr.sqlite
uv run eddr db load-sources --db data/eddr.sqlite --eda-cache data/eda_cache --takeout-manifest data/google_photos/manifest.jsonl --photos-export data/photos_export
```

Materialize missing iCloud/Photos assets when needed:

```bash
uv run eddr photos export --print-only
uv run eddr photos export
```

Run local Vision caption + embedding batches:

```bash
uv run eddr vision run --db data/eddr.sqlite --chroma data/index/chroma --limit 100
```

Search indexed captions:

```bash
uv run eddr search semantic "해변 불빛" --db data/eddr.sqlite --chroma data/index/chroma --k 10
```

## Current Status

Verified on 2026-06-07:

- Source load completed: `loaded=11696 skipped=473 errors=0`.
- SQLite `photos`: 11,689 rows.
- Photo statuses: `caption_done=1`, `meta_done=3114`, `missing_image=8574`.
- Captions: 1 row.
- Embeddings: 1 `caption_text` row using `qwen3-embedding:8b`.
- Chroma collection `eddr_caption_text_v1`: 1 vector.
- Test suite: 33 passing tests.

The full Vision caption load is not complete yet. The next operational step is
to materialize missing Photos assets, reload sources, then run resumable Vision
batches until remaining `meta_done` rows are processed.

## Documentation

- [Foundation DB usage and status](docs/FOUNDATION_DB_USAGE.md)
- [ADR-0006: Vector Store Selection](docs/adr/0006-vector-store-selection.md)
- [Wiki index](wiki/WIKI_INDEX.md)

"""상태 라우트 — 인덱싱 통계 + 경로 계약 헬스 (prd §6-b, FR-STATUS-1)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from eddr.db.repository import PhotoQueryFilters
from eddr.server.deps import AppState, get_state, resolve_image_path

router = APIRouter(prefix="/api", tags=["status"])

# path_health 표본 크기 — 노출 사진(geocode 우선·최신순) 상위에서 뽑는다.
# 상대경로 소스(photos_library·takeout)가 대부분이라 EDDR_ROOT 오설정이 바로 드러난다.
_HEALTH_SAMPLE = 20


@router.get("/healthz")
def healthz() -> dict:
    """liveness 체크 — 의존 리소스를 건드리지 않는다."""
    return {"ok": True}


@router.get("/status")
def status(state: Annotated[AppState, Depends(get_state)]) -> dict:
    """인덱싱 상태 + 경로 헬스 — ``{ready, total, stages, path_health}`` (prd §6-b)."""
    stats = state.service.db.indexing_stats()
    stages = state.service.db.indexing_stage_counts()
    photos = state.service.db.query_photos(PhotoQueryFilters(), limit=_HEALTH_SAMPLE)
    resolved = [
        resolve_image_path(state.config.root, photo.image_path)
        for photo in photos
        if photo.image_path
    ]
    ok = sum(1 for path in resolved if path.is_file())
    return {
        "ready": stats.ready,
        "total": stats.total,
        "stages": stages,
        "path_health": {
            "sampled": len(resolved),
            "ok": ok,
            "healthy": bool(resolved) and ok == len(resolved),
        },
    }

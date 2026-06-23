"""지도 라우트 — 노출 GPS 점 GeoJSON 일괄 (prd §6-b, FR-MAP-1, S1).

좌표의 "내 서버 → 내 브라우저" 노출은 ADR-0009 §3으로 허용된다 — 질의 레이어
privacy dataclass를 거치지 않고 server 전용 repo 메서드로 직접 서빙한다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from eddr.server.deps import AppState, get_state

router = APIRouter(prefix="/api/map", tags=["map"])

# GeoJSON 일괄 캐시 — 위치 지정(M4) 후 클라이언트가 강제 재요청한다(prd §6-b).
_CACHE_MAX_AGE = 300


@router.get("/photos")
def map_photos(state: Annotated[AppState, Depends(get_state)], response: Response) -> dict:
    """노출 GPS 점 전량을 GeoJSON FeatureCollection으로 반환한다 — 지도 클러스터 소스.

    좌표는 ``[lng, lat]`` 순서(GeoJSON 규약)다. properties에 photo_id와 KST
    달력일(date)만 실어 페이로드를 줄인다 — 상세는 by-date·detail로 따로 받는다.
    """
    points = state.service.db.exposed_gps_points()
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [point.longitude, point.latitude]},
            "properties": {"id": point.photo_id, "date": point.date},
        }
        for point in points
    ]
    response.headers["Cache-Control"] = f"private, max-age={_CACHE_MAX_AGE}"
    return {"type": "FeatureCollection", "features": features}

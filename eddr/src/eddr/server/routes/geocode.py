"""지오코드 라우트 — Nominatim /search 서버 프록시 (D26 M4, prd §6-b, S4).

브라우저의 Nominatim 직접 호출 금지 계약(ADR-0009 §3) — UA 식별·1 req/s를
서버의 NominatimClient 한 인스턴스로 일원화한다. 블로킹 urllib 호출이라
sync 라우트(threadpool)로 둔다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from eddr.geocode.nominatim import GeocodeError
from eddr.server.deps import AppState, get_state

router = APIRouter(prefix="/api/geocode", tags=["geocode"])


@router.get("/search")
def geocode_search(q: str, state: Annotated[AppState, Depends(get_state)]) -> dict:
    """장소 검색어의 좌표 후보 ≤5 — GeocodeFlow의 후보 리스트·지도 핀 입력.

    Nominatim 장애·네트워크 오류는 502 — 후보 0건(200 + 빈 candidates)과
    구분된다. 0건일 때의 long-press 안내는 클라이언트 책임.
    """
    query = q.strip()
    if not query:
        raise HTTPException(status_code=422, detail="q가 비어 있습니다.")
    try:
        candidates = state.geocoder.search(query)
    except GeocodeError as exc:
        raise HTTPException(status_code=502, detail=f"Nominatim 요청 실패: {exc}") from exc
    return {
        "candidates": [
            {
                "name": candidate.name,
                "latitude": candidate.latitude,
                "longitude": candidate.longitude,
                "type": candidate.type,
                "address": {
                    "country": candidate.address.country,
                    "city": candidate.address.city,
                    "district": candidate.address.district,
                },
            }
            for candidate in candidates
        ]
    }

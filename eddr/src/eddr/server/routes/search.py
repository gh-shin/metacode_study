"""검색 라우트 — 추출→trip 스코프→RRF 검색→KST 날짜 그룹핑 (D26 M3, prd §6-b·§6-c).

읽기 전용·무상태 — 구 chat_lock 같은 직렬화가 없다. ollama 동시성은 ollama
큐에 위임한다. 추출(gemma4:e2b)·임베딩(qwen3-embedding) 호출이 블로킹이라
전체 파이프라인을 threadpool에서 돌린다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from eddr.query.extract import ExtractedQuery, QueryExtractor
from eddr.query.tools import PhotoSummary, QueryService
from eddr.server.deps import AppState, get_state

router = APIRouter(prefix="/api", tags=["search"])

# 한 번의 검색이 가져오는 최대 사진 수 — QueryService MAX_LIMIT와 동일.
_SEARCH_K = 50
_OLLAMA_DOWN_DETAIL = "로컬 모델 서버(ollama)가 꺼져 있어요. ollama serve 후 다시 시도해 주세요."


@dataclass(frozen=True)
class LanePhoto:
    """lane 한 칸의 사진 — 좌표 동봉으로 지도 하이라이트 입력을 겸한다 (ADR-0009 §3).

    Attributes:
        photo_id: 사진 식별자 — 썸네일·상세 조회 키.
        taken_at: 촬영 시각 (KST aware ISO).
        latitude: GPS 위도. 없으면 None.
        longitude: GPS 경도. 없으면 None.
        rank: 검색 관련도 순위 (1부터).
    """

    photo_id: str
    taken_at: str | None
    latitude: float | None
    longitude: float | None
    rank: int | None


@dataclass(frozen=True)
class SearchLane:
    """KST 달력일 lane 하나 — 관련도순 정렬(그룹 내 최고 rank)의 단위 (S2, D26-⑦).

    Attributes:
        date: KST 달력일 (YYYY-MM-DD). taken_at 없는 사진 그룹은 None.
        place: 그룹 대표 장소 — 최빈 city(없으면 country, 둘 다 없으면 None).
        photos: 그룹 사진 (rank 오름차순).
    """

    date: str | None
    place: str | None
    photos: tuple[LanePhoto, ...]


@router.post("/search")
async def search(
    payload: Annotated[dict, Body()],
    state: Annotated[AppState, Depends(get_state)],
) -> dict:
    """한국어 질의 한 건을 검색한다 — ``{interpretation, groups, total}`` (prd §6-b).

    추출(gemma4:e2b) → 지명 매칭 trip_ids 도출 → semantic_search_photos
    (원문 질의 + keywords_en RRF) → KST 달력일 그룹핑. 그룹 정렬은 그룹 내
    최고 rank(관련도, D26-⑦)이고 그룹 내부도 rank순이다.
    """
    query = str(payload.get("query", "")).strip()
    if not query:
        raise HTTPException(status_code=422, detail="query가 비어 있습니다.")
    try:
        extracted, results = await run_in_threadpool(
            run_search, state.extractor, state.service, query
        )
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=_OLLAMA_DOWN_DETAIL) from exc
    lanes = group_by_kst_date(results, order_by_date=is_date_intent(query))
    return {
        "interpretation": asdict(extracted),
        # SearchLane → dict 직렬화는 라우트 가장자리에서만 — 내부 소비처(골든 러너)는
        # 객체 그대로 받는다. asdict가 중첩 dataclass·tuple을 재귀 변환한다.
        "groups": [asdict(lane) for lane in lanes],
        "total": len(results),
    }


def run_search(
    extractor: QueryExtractor, service: QueryService, query: str
) -> tuple[ExtractedQuery, list[PhotoSummary]]:
    """추출→trip 스코프→검색을 동기 실행한다 — 라우트(threadpool)와 golden 러너 공용.

    골든셋 v2 자동 채점(``eddr golden``)이 HTTP 비경유로 같은 코어 경로를 타도록
    AppState 대신 추출기·서비스를 직접 받는다. ollama 연결 불가 ``ConnectionError``는
    그대로 전파한다 — 라우트는 503으로, 러너는 즉시 중단으로 처리한다 (prd §6-c).
    """
    extracted = extractor.extract(query)
    trip_ids: list[str] = []
    if extracted.countries or extracted.cities:
        # 지명 → trip 도출 — GPS 무 사진을 trip 소속으로 건진다 (구 list_trips 역할 대체).
        trip_ids = service.db.trip_ids_for_places(extracted.countries, extracted.cities)
    results = service.semantic_search_photos(
        query=query,  # 임베딩 질의는 원문 한국어 유지 (prd §6-c)
        k=_SEARCH_K,
        date_from=extracted.date_from,
        date_to=extracted.date_to,
        countries=list(extracted.countries),
        cities=list(extracted.cities),
        trip_ids=trip_ids,
        keywords=list(extracted.keywords_en),
    )
    return extracted, results


_DATE_INTENT_RE = re.compile(r"언제|몇\s*년|몇\s*월|며칠")


def is_date_intent(query: str) -> bool:
    """질의가 명시적 시간(날짜/사실) 의문인지 판정한다 — lane을 날짜순으로 정렬할지 결정.

    "언제"·"몇 년"·"몇 월"·"며칠" 등 시간 의문사만 매칭한다. "여행"·"사진" 같은
    일반어는 비매칭이라 photo_list 질의의 lane 순서(관련도)를 보존한다.

    Args:
        query: 사용자 한국어 질의 원문.

    Returns:
        시간 의문사가 있으면 True.
    """
    return bool(_DATE_INTENT_RE.search(query))


def group_by_kst_date(results: list[PhotoSummary], order_by_date: bool = False) -> list[SearchLane]:
    """검색 결과를 KST 달력일 lane으로 묶는다.

    taken_at은 전량 KST aware ISO(D26 M1)라 앞 10자가 KST 달력일이다.
    taken_at 없는 사진은 date=None 그룹으로 모은다. place는 그룹 최빈
    city(없으면 country, 둘 다 없으면 None)다.

    order_by_date=True면(날짜/사실 질의) lane을 날짜 오름차순(가장 이른 날 = trip
    시작일 top, date 없는 그룹은 말미)으로, False면(기본) 그룹 최고 관련도순으로 정렬한다.
    그룹 *내부* 사진 순서(rank 오름차순)는 두 경우 모두 유지한다.
    """
    by_date: dict[str | None, list[PhotoSummary]] = {}
    for photo in results:
        date = photo.taken_at[:10] if photo.taken_at else None
        by_date.setdefault(date, []).append(photo)
    if order_by_date:
        # 날짜/사실 질의 — 가장 이른 날(trip 시작일)을 top으로, date 없는 그룹은 말미.
        ordered = sorted(by_date.items(), key=lambda item: (item[0] is None, item[0] or ""))
    else:
        # semantic 결과는 rank 오름차순이라 그룹 내 첫 사진의 rank가 그룹 최고 관련도다.
        ordered = sorted(by_date.items(), key=lambda item: item[1][0].rank)
    return [
        SearchLane(
            date=date,
            place=_majority_place(photos),
            photos=tuple(
                LanePhoto(
                    photo_id=photo.photo_id,
                    taken_at=photo.taken_at,
                    latitude=photo.latitude,
                    longitude=photo.longitude,
                    rank=photo.rank,
                )
                for photo in photos
            ),
        )
        for date, photos in ordered
    ]


def _majority_place(photos: list[PhotoSummary]) -> str | None:
    """그룹 대표 장소 — 최빈 city, 없으면 최빈 country, 둘 다 없으면 None."""
    for values in ([p.city for p in photos if p.city], [p.country for p in photos if p.country]):
        if values:
            return Counter(values).most_common(1)[0][0]
    return None

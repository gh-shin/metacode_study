"""사진 라우트 — 상세(좌표 포함)·by-date·위치 미상/지정·썸네일·원본 (prd §6-b·§6-c)."""

from __future__ import annotations

import mimetypes
import re
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse

from eddr.db.repository import GeocodeCacheEntry
from eddr.geocode.nominatim import GeocodeError
from eddr.geocode.pipeline import quantize
from eddr.server.deps import AppState, get_state, resolve_image_path
from eddr.server.thumbnails import ALLOWED_SIZES, get_thumbnail

router = APIRouter(prefix="/api/photos", tags=["photos"])

# summary 1회 요청당 id 상한 — 더 긴 목록은 클라이언트가 분할 호출한다.
_SUMMARY_MAX_IDS = 50
# 메모 길이 상한 — 임베딩 비용·모델 입력 잘림·라이트박스 패널 밀림 방어(M5 리뷰 I4).
NOTE_MAX_CHARS = 2000
# by-date 날짜 형식 — KST 달력일 YYYY-MM-DD만 허용(형식 불일치는 422).
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# 메모 임베딩 kind — embeddings 복합 PK(photo_id, kind, model_id) 재사용 (prd §6-d).
_NOTE_KIND = "note_text"


@router.get("/summary")
def photo_summaries(ids: str, state: Annotated[AppState, Depends(get_state)]) -> dict:
    """photo_id 목록의 경량 요약(날짜·장소).

    현재 SPA는 미사용(구 채팅 lane UI의 소비처가 D26 M3에서 삭제됨) —
    prd v2 §6-b의 "유지" 결정에 따라 스크립트·외부 호출용으로 보존한다.
    입력 순서를 유지하고 미존재 id는 건너뛴다. duplicate는 canonical 메타를
    따르되 photo_id는 요청 값을 유지한다(썸네일 URL 일관성). `/{photo_id}`
    보다 먼저 등록해야 경로 매칭이 가로채이지 않는다.
    """
    requested = [pid.strip() for pid in ids.split(",") if pid.strip()][:_SUMMARY_MAX_IDS]
    photos = []
    for pid in requested:
        photo = state.service.db.get_photo(pid)
        if photo is not None and photo.duplicate_of:
            photo = state.service.db.get_photo(photo.duplicate_of)
        if photo is None:
            continue
        photos.append(
            {
                "photo_id": pid,
                "taken_at": photo.taken_at,
                "country": photo.country,
                "city": photo.city,
                "has_location": photo.latitude is not None and photo.longitude is not None,
            }
        )
    return {"photos": photos}


@router.get("/by-date")
def photos_by_date(date: str, state: Annotated[AppState, Depends(get_state)]) -> dict:
    """특정 KST 달력일의 노출 사진 전부 — 날짜 상세 그리드용 (S3, FR-MAP-3).

    좌표를 동봉해(ADR-0009 §3) 지도 fitBounds 입력으로 쓴다. GPS 없는 사진도
    포함된다. `/{photo_id}` 보다 먼저 등록해야 경로 매칭이 가로채이지 않는다.
    """
    if not _DATE_RE.match(date):
        raise HTTPException(status_code=422, detail="date는 YYYY-MM-DD 형식이어야 합니다.")
    rows = state.service.db.exposed_photos_by_date(date)
    photos = [
        {
            "photo_id": row["id"],
            "taken_at": row["taken_at"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "country": row["country"],
            "city": row["city"],
        }
        for row in rows
    ]
    return {"date": date, "photos": photos}


@router.get("/no-location")
def no_location_groups(state: Annotated[AppState, Depends(get_state)]) -> dict:
    """위치 미상 사진의 KST 일별 그룹 전량 — 빨간 배지·드로어 입력 (S4, prd §6-b).

    가치순 정렬(trip·장수 우선, 동률 date DESC)·trip 힌트는 repo(no_location_day_groups)가 책임진다.
    `/{photo_id}` 보다 먼저 등록해야 경로 매칭이 가로채이지 않는다.
    """
    groups = state.service.db.no_location_day_groups()
    return {"total_photos": sum(group["count"] for group in groups), "groups": groups}


@router.put("/location")
def set_photo_location(
    payload: Annotated[dict, Body()],
    state: Annotated[AppState, Depends(get_state)],
) -> dict:
    """일괄 수동 위치 지정 — 좌표 직접 갱신 + location_source='manual' (ADR-0009 §4).

    주소(country/city/district)는 forward 후보 표기를 쓰지 않고 기존 reverse
    경로(양자화 캐시 → Nominatim reverse → photos 갱신)로 통일한다. Nominatim
    실패 시에도 좌표 저장은 성공으로 두고 주소 필드만 null로 반환한다 —
    해당 셀은 캐시에 안 남아 다음 `eddr geocode` 배치가 재시도한다.
    blocking reverse 호출이 있어 sync 라우트(threadpool)로 둔다.
    """
    photo_ids = payload.get("photo_ids")
    if (
        not isinstance(photo_ids, list)
        or not photo_ids
        or not all(isinstance(photo_id, str) for photo_id in photo_ids)
    ):
        raise HTTPException(
            status_code=422, detail="photo_ids는 비어 있지 않은 문자열 목록이어야 합니다."
        )
    try:
        latitude = float(payload.get("latitude"))  # type: ignore[arg-type]
        longitude = float(payload.get("longitude"))  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail="latitude/longitude는 숫자여야 합니다."
        ) from exc
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        raise HTTPException(status_code=422, detail="좌표가 위경도 범위를 벗어났습니다.")
    updated = state.service.db.update_photo_location(photo_ids, latitude, longitude)
    address = _fill_address(state, photo_ids, latitude, longitude)
    country, city, district = address if address else (None, None, None)
    return {"updated": updated, "country": country, "city": city, "district": district}


@router.put("/note/by-date")
def put_notes_by_date(
    payload: Annotated[dict, Body()],
    state: Annotated[AppState, Depends(get_state)],
) -> dict:
    """같은 KST 달력일의 노트 없는 사진에 동일 메모 일괄 적용 — 빈 사진만 채움.

    그날 노출 사진(exposed_photos_by_date) 중 get_note가 None인 사진에만
    upsert_note + 동기 임베딩한다. 이미 노트가 있는 사진은 건드리지 않는다
    (덮어쓰기 없음). 단일 노트 저장과 동일하게 임베딩 실패는 저장을 막지
    않으며 embedded 카운트에서만 빠진다. blocking 임베딩이 있어 sync 라우트.
    """
    date = payload.get("date")
    text = payload.get("text")
    if not isinstance(date, str) or not _DATE_RE.match(date):
        raise HTTPException(status_code=422, detail="date는 YYYY-MM-DD 형식이어야 합니다.")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=422, detail="text는 비어 있지 않은 문자열이어야 합니다.")
    text = text.strip()
    if len(text) > NOTE_MAX_CHARS:
        raise HTTPException(status_code=422, detail=f"메모는 {NOTE_MAX_CHARS:,}자 이하여야 합니다.")
    applied = 0
    embedded = 0
    for row in state.service.db.exposed_photos_by_date(date):
        pid = row["id"]
        if state.service.db.get_note(pid) is not None:
            continue
        state.service.db.upsert_note(pid, text)
        if _embed_note(state, pid, text):
            embedded += 1
        applied += 1
    return {"applied": applied, "embedded": embedded}


def _fill_address(
    state: AppState, photo_ids: list[str], latitude: float, longitude: float
) -> tuple[str | None, str | None, str | None] | None:
    """수동 지정 좌표의 행정구역을 기존 reverse 경로로 채운다 (ADR-0009 §4).

    geocode 파이프라인(geocode_photos)과 동일 규약 — 양자화 셀 캐시를 먼저
    보고, miss면 셀 중심을 reverse 조회해 캐시 적재 후 photos에 기록한다.
    실패 시 None — 좌표 저장은 유지되고 index_errors에 남는다.
    """
    db = state.service.db
    lat_q, lng_q = quantize(latitude), quantize(longitude)
    cached = db.get_geocode_cache(lat_q, lng_q)
    if cached is None:
        try:
            result = state.geocoder.reverse(lat_q / 1000, lng_q / 1000)
        except GeocodeError as exc:
            db.record_error(None, "manual_location", str(exc))
            return None
        db.upsert_geocode_cache(
            lat_q, lng_q, result.country, result.city, result.district, result.country_code
        )
        cached = GeocodeCacheEntry(
            country=result.country,
            city=result.city,
            district=result.district,
            country_code=result.country_code,
        )
    for photo_id in photo_ids:
        db.update_photo_geo(photo_id, cached.country, cached.city, cached.district)
    return (cached.country, cached.city, cached.district)


@router.get("/{photo_id}")
def photo_detail(photo_id: str, state: Annotated[AppState, Depends(get_state)]) -> dict:
    """사진 단건 상세 — get_photo tool 스키마 + 좌표(ADR-0009 §3, 지도·라이트박스용).

    좌표는 privacy dataclass(PhotoDetail)에 없으므로 server 레이어에서 repo를
    직접 조회해 merge한다. duplicate는 detail이 canonical로 따라가므로 좌표도
    canonical 행에서 읽어 일관성을 맞춘다.
    """
    photo = state.service.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다.")
    body = asdict(photo)
    record = state.service.db.get_photo(photo_id)
    if record is not None and record.duplicate_of:
        record = state.service.db.get_photo(record.duplicate_of)
    body["latitude"] = record.latitude if record else None
    body["longitude"] = record.longitude if record else None
    # 메모(S5) — canonical 귀속(photo.photo_id는 위에서 canonical로 따라간 id).
    body["note"] = state.service.db.get_note(photo.photo_id)
    return body


@router.put("/{photo_id}/note")
def put_photo_note(
    photo_id: str,
    payload: Annotated[dict, Body()],
    state: Annotated[AppState, Depends(get_state)],
) -> dict:
    """메모 upsert + 동기 임베딩 — 사진별 1메모 (S5, prd §6-b).

    임베딩이 실패해도 메모 저장은 성공으로 두고 embedded=false를 반환한다 —
    미임베딩 메모는 embeddings에 행이 없어 추후 재임베딩 대상으로 식별된다.
    duplicate는 canonical에 귀속시켜 검색 노출 모집단과 정체성을 맞춘다
    (ADR-0002). blocking 임베딩 호출이 있어 sync 라우트(threadpool)로 둔다.
    """
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=422, detail="text는 비어 있지 않은 문자열이어야 합니다.")
    if len(text.strip()) > NOTE_MAX_CHARS:
        raise HTTPException(status_code=422, detail=f"메모는 {NOTE_MAX_CHARS:,}자 이하여야 합니다.")
    photo = _canonical_photo(state, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다.")
    text = text.strip()
    state.service.db.upsert_note(photo.id, text)
    embedded = _embed_note(state, photo.id, text)
    return {"photo_id": photo.id, "text": text, "embedded": embedded}


@router.delete("/{photo_id}/note", status_code=204)
def delete_photo_note(photo_id: str, state: Annotated[AppState, Depends(get_state)]) -> None:
    """메모 삭제 — notes 행 + Chroma 벡터 + embeddings 행 일괄 (S5, prd §6-b).

    벡터부터 지운다 — 도중 실패 시 메모가 남아 재시도할 수 있다(반대 순서는
    메모 없는 사진이 note leg에 잔류하는 고아를 만든다). 메모가 없으면 404.
    """
    photo = _canonical_photo(state, photo_id)
    if photo is None or state.service.db.get_note(photo.id) is None:
        raise HTTPException(status_code=404, detail="메모를 찾을 수 없습니다.")
    vector_ids = state.service.db.embedding_vector_ids(photo.id, _NOTE_KIND)
    if vector_ids and state.note_store is not None:
        state.note_store.delete(vector_ids)
    state.service.db.delete_note(photo.id)
    state.service.db.delete_embedding_records(photo.id, _NOTE_KIND)


def _canonical_photo(state: AppState, photo_id: str):
    """duplicate 마킹이면 canonical 행으로 따라간 PhotoRecord — 없으면 None."""
    photo = state.service.db.get_photo(photo_id)
    if photo is not None and photo.duplicate_of:
        photo = state.service.db.get_photo(photo.duplicate_of)
    return photo


def _embed_note(state: AppState, photo_id: str, text: str) -> bool:
    """메모를 동기 임베딩해 Chroma(eddr_note_text_v1)·embeddings에 기록한다.

    문서(메모) 측은 instruct prefix 없이 임베딩한다 — 질의 측만 붙는 캡션 leg
    규약과 동일 (prd §6-d). 실패(ollama 다운 등)는 index_errors에 남기고
    False를 반환한다 — notes 저장은 유지된다(S5 수용 기준).
    """
    client = state.service.embedding_client
    if client is None or state.note_store is None:
        return False
    try:
        vector = client.embed_texts([text])[0]
        model_id = client.embedding_model
        vector_id = f"{_NOTE_KIND}:{photo_id}:{model_id}"
        state.note_store.upsert(
            ids=[vector_id],
            embeddings=[vector],
            documents=[text],
            metadatas=[{"photo_id": photo_id}],
        )
        state.service.db.upsert_embedding_record(
            photo_id=photo_id,
            kind=_NOTE_KIND,
            model_id=model_id,
            vector_id=vector_id,
            dimensions=len(vector),
        )
        return True
    except Exception as exc:  # 임베딩 실패가 저장을 막으면 안 된다 (S5)
        state.service.db.record_error(photo_id, "note_embed", str(exc))
        return False


@router.get("/{photo_id}/thumb")
def photo_thumb(
    photo_id: str,
    state: Annotated[AppState, Depends(get_state)],
    size: int = 320,
) -> FileResponse:
    """JPEG 썸네일 — size는 {320, 1280} 화이트리스트만 (ADR-0008).

    sync 라우트라 FastAPI가 threadpool에서 실행한다 — PIL 변환이 이벤트
    루프를 막지 않는다. 경로는 photo_id → DB → resolve 간접 참조만.
    """
    if size not in ALLOWED_SIZES:
        raise HTTPException(status_code=422, detail=f"size는 {ALLOWED_SIZES} 중 하나여야 합니다.")
    path_str = state.service.image_path(photo_id)
    if not path_str:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다.")
    source = resolve_image_path(state.config.root, path_str)
    if not source.is_file():
        raise HTTPException(
            status_code=404, detail="원본 파일이 없습니다 — EDDR_ROOT 설정을 확인하세요."
        )
    thumb = get_thumbnail(source, state.thumb_dir, photo_id, size)
    if thumb is None:
        raise HTTPException(status_code=500, detail="썸네일 변환에 실패했습니다.")
    # 캐시 키 {photo_id}_{size}는 내용 불변(ADR-0008) — 1일 immutable로 지도
    # 팬·재방문 시 재요청을 없앤다(모바일 썸네일 표출 체감, M2 피드백 ①).
    return FileResponse(
        thumb,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=86400, immutable"},
    )


@router.get("/{photo_id}/original")
def photo_original(photo_id: str, state: Annotated[AppState, Depends(get_state)]) -> FileResponse:
    """원본 스트림(저장용) — HEIC 등 포맷 그대로, Content-Disposition 첨부 (M2).

    노출되는 파일명은 경로 없는 basename뿐이다 (ADR-0008 절대경로 미노출).
    """
    path_str = state.service.image_path(photo_id)
    if not path_str:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다.")
    source = resolve_image_path(state.config.root, path_str)
    if not source.is_file():
        raise HTTPException(
            status_code=404, detail="원본 파일이 없습니다 — EDDR_ROOT 설정을 확인하세요."
        )
    media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    return FileResponse(source, media_type=media_type, filename=source.name)

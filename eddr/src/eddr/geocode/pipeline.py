"""geocode 파이프라인 — 양자화 캐시를 거쳐 photos.country/city/district를 채운다."""

from __future__ import annotations

from dataclasses import dataclass

from eddr.db.repository import EddrDatabase, GeocodeCacheEntry
from eddr.geocode.nominatim import GeocodeError, NominatimClient


@dataclass(frozen=True)
class GeocodeReport:
    """geocode 배치 결과 요약.

    Attributes:
        photos_updated: 행정구역 필드가 갱신된 사진 수.
        cells_fetched: Nominatim에 실제 요청한 셀 수.
        cache_hits: geocode_cache 적중 수.
        errors: 요청 실패 수 (index_errors 기록).
        aborted: 연속 실패 한도로 중단됐으면 True.
    """

    photos_updated: int = 0
    cells_fetched: int = 0
    cache_hits: int = 0
    errors: int = 0
    aborted: bool = False


@dataclass(frozen=True)
class CountryCodeBackfillReport:
    """ISO country_code 백필 결과 요약.

    Attributes:
        cells_updated: country_code가 채워진 캐시 셀 수.
        errors: 요청 실패 수 (index_errors 기록).
        aborted: 연속 실패 한도로 중단됐으면 True.
    """

    cells_updated: int = 0
    errors: int = 0
    aborted: bool = False


def quantize(value: float) -> int:
    """좌표를 3dp 밀리도(0.001°, 약 110m) 격자로 양자화한다.

    실측(2026-06-10) 기준 GPS 7,888장이 2,047셀로 줄어 1 req/s로 약 34분.
    """
    return round(value * 1000)


def geocode_photos(
    db: EddrDatabase,
    client: NominatimClient,
    limit: int | None = None,
    max_consecutive_errors: int = 5,
) -> GeocodeReport:
    """GPS는 있고 country가 빈 사진의 행정구역 필드를 채운다.

    같은 양자화 셀은 캐시로 1회만 요청하며, 요청 좌표는 캐시 정합성을 위해
    원좌표가 아닌 셀 중심을 쓴다. 요청 실패는 index_errors(stage='geocode')에
    기록하고 다음 사진으로 진행하되, 연속 max_consecutive_errors회 실패하면
    서버 장애로 보고 중단한다(aborted=True). 주소 없는 좌표(바다 등)는 전 필드
    None으로 캐시·기록되며, country가 NULL로 남아 다음 실행에서 재선택되지만
    캐시 적중이라 재요청은 발생하지 않는다.

    Args:
        db: 대상 데이터베이스.
        client: NominatimClient 또는 동일 시그니처의 reverse()를 가진 객체.
        limit: 처리할 최대 사진 수. None이면 전체.
        max_consecutive_errors: 중단 임계 연속 실패 횟수.

    Returns:
        갱신·요청·캐시·오류 수를 담은 GeocodeReport.
    """
    photos_updated = cells_fetched = cache_hits = errors = 0
    consecutive_errors = 0
    aborted = False
    for photo in db.photos_needing_geocode(limit):
        lat_q, lng_q = quantize(photo.latitude), quantize(photo.longitude)
        cached = db.get_geocode_cache(lat_q, lng_q)
        if cached is None:
            try:
                result = client.reverse(lat_q / 1000, lng_q / 1000)
            except GeocodeError as exc:
                db.record_error(photo.id, "geocode", str(exc))
                errors += 1
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    aborted = True
                    break
                continue
            consecutive_errors = 0
            db.upsert_geocode_cache(
                lat_q, lng_q, result.country, result.city, result.district, result.country_code
            )
            cells_fetched += 1
            cached = GeocodeCacheEntry(
                country=result.country,
                city=result.city,
                district=result.district,
                country_code=result.country_code,
            )
        else:
            cache_hits += 1
        # photos에는 행정구역명만 기록 — country_code는 캐시에만 두고 trip 단계가 셀 단위로 조회.
        db.update_photo_geo(photo.id, cached.country, cached.city, cached.district)
        photos_updated += 1
    return GeocodeReport(
        photos_updated=photos_updated,
        cells_fetched=cells_fetched,
        cache_hits=cache_hits,
        errors=errors,
        aborted=aborted,
    )


def backfill_country_codes(
    db: EddrDatabase,
    client: NominatimClient,
    max_consecutive_errors: int = 5,
) -> CountryCodeBackfillReport:
    """country는 있으나 country_code가 빈 캐시 셀을 재조회해 ISO 코드를 채운다.

    ④ geocode 배치는 country_code를 보존하지 않았다 — 이미 채워진 지명 필드는
    건드리지 않고 코드만 갱신하는 1회성 백필이다(이후 신규 조회는 코드를 함께
    저장한다). 요청 좌표는 본배치와 동일하게 셀 중심을 쓴다. negative cache는
    대상에서 빠지며, 실패는 index_errors(stage='country_code_backfill')에 기록
    후 계속하되 연속 max_consecutive_errors회면 중단한다(aborted=True).

    Args:
        db: 대상 데이터베이스.
        client: NominatimClient 또는 동일 시그니처의 reverse()를 가진 객체.
        max_consecutive_errors: 중단 임계 연속 실패 횟수.

    Returns:
        갱신 셀·오류 수를 담은 CountryCodeBackfillReport.
    """
    cells_updated = errors = 0
    consecutive_errors = 0
    aborted = False
    for lat_q, lng_q in db.geocode_cells_missing_country_code():
        try:
            result = client.reverse(lat_q / 1000, lng_q / 1000)
        except GeocodeError as exc:
            db.record_error(None, "country_code_backfill", str(exc))
            errors += 1
            consecutive_errors += 1
            if consecutive_errors >= max_consecutive_errors:
                aborted = True
                break
            continue
        consecutive_errors = 0
        db.update_geocode_cache_country_code(lat_q, lng_q, result.country_code)
        cells_updated += 1
    return CountryCodeBackfillReport(cells_updated=cells_updated, errors=errors, aborted=aborted)

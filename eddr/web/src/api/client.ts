// API 클라이언트 단일 모듈 — 모든 서버 호출이 여기를 거친다.
// 멀티유저 전환(M5) 시 인증 토큰 주입점이 이 파일 하나로 모인다 (prd §6-e 규율 ③).

export interface PhotoDetail {
  photo_id: string
  taken_at: string | null
  country: string | null
  city: string | null
  district: string | null
  has_location: boolean
  caption: string | null
  keywords: string[]
  trip_id: string | null
  trip_name: string | null
  width: number | null
  height: number | null
  camera_make: string | null
  camera_model: string | null
  latitude: number | null
  longitude: number | null
  note: string | null
}

// PUT /api/photos/{id}/note 응답 — embedded:false면 저장만 되고 검색 미반영(ollama 다운).
export interface NoteResponse {
  photo_id: string
  text: string
  embedded: boolean
}

// PUT /api/photos/note/by-date — 같은 날 노트 없는 사진에만 일괄 적용(빈 사진만 채움).
export interface NoteByDateResponse {
  applied: number
  embedded: number
}

// /api/search 해석 결과 — 칩 줄 표시용(오해석을 사용자가 즉시 인지, prd §6-b).
export interface SearchInterpretation {
  keywords_en: string[]
  keywords_ko: string[]
  answer_type: string
  date_from: string | null
  date_to: string | null
  countries: string[]
  cities: string[]
  fallback: boolean
}

export interface SearchPhoto {
  photo_id: string
  taken_at: string | null
  latitude: number | null
  longitude: number | null
  rank: number
}

// KST 달력일 lane — date=null은 촬영 시각 미상 그룹. 정렬은 그룹 내 최고 rank(관련도).
export interface SearchGroup {
  date: string | null
  place: string | null
  photos: SearchPhoto[]
}

export interface TripSummary {
  trip_id: string
  name: string
  start_at: string
  end_at: string
  photo_count: number
  country_codes: string[]
}

export interface SearchResponse {
  interpretation: SearchInterpretation
  groups: SearchGroup[]
  trip_summary: TripSummary[]
  total: number
}

// /api/photos/by-date 응답 사진 — 좌표 동봉(ADR-0009 §3, 지도 fitBounds용).
export interface DatePhoto {
  photo_id: string
  taken_at: string | null
  latitude: number | null
  longitude: number | null
  country: string | null
  city: string | null
}

export interface ByDateResponse {
  date: string
  photos: DatePhoto[]
}

// /api/photos/no-location — 위치 미상 KST 일별 그룹(M4). date DESC 정렬.
export interface NoLocationGroup {
  date: string
  count: number
  sample_photo_ids: string[]
  trip_name: string | null
  focus_photo_id?: string
}

export interface NoLocationResponse {
  total_photos: number
  groups: NoLocationGroup[]
}

export interface GeocodeAddress {
  country: string | null
  city: string | null
  district: string | null
}

// /api/geocode/search 후보 — Nominatim 서버 프록시(UA·1 req/s 일원화, ADR-0009 §3).
export interface GeocodeCandidate {
  name: string
  latitude: number
  longitude: number
  type: string | null
  address: GeocodeAddress
}

export interface GeocodeSearchResponse {
  candidates: GeocodeCandidate[]
}

// PUT /api/photos/location 응답 — 주소는 reverse 경로(실패 시 전부 null).
export interface LocationUpdateResponse {
  updated: number
  country: string | null
  city: string | null
  district: string | null
}

// /api/map/photos GeoJSON — properties는 id·date만.
export interface MapFeature {
  type: 'Feature'
  geometry: { type: 'Point'; coordinates: [number, number] }
  properties: { id: string; date: string }
}

export interface MapPhotosResponse {
  type: 'FeatureCollection'
  features: MapFeature[]
}

export interface StatusResponse {
  ready: number
  total: number
  stages: Record<string, number>
  path_health: { sampled: number; ok: number; healthy: boolean }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    // FastAPI 오류 본문 {detail}을 사용자 메시지로 그대로 노출.
    let detail = `HTTP ${response.status}`
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      /* 본문이 JSON이 아니면 상태 코드 문자열 유지 */
    }
    throw new Error(detail)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  detail: (photoId: string) =>
    request<PhotoDetail>(`/api/photos/${encodeURIComponent(photoId)}`),
  // 자연어 검색(M3) — 503(ollama 다운) detail은 request가 Error.message로 노출한다.
  search: (query: string) =>
    request<SearchResponse>('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    }),
  status: () => request<StatusResponse>('/api/status'),
  // force: 위치 지정(M4) 직후 HTTP 캐시(max-age=300)를 우회해 새 마커를 받는다.
  mapPhotos: (force = false) =>
    request<MapPhotosResponse>('/api/map/photos', force ? { cache: 'reload' } : undefined),
  photosByDate: (date: string) =>
    request<ByDateResponse>(`/api/photos/by-date?date=${encodeURIComponent(date)}`),
  noLocation: () => request<NoLocationResponse>('/api/photos/no-location'),
  geocodeSearch: (q: string) =>
    request<GeocodeSearchResponse>(`/api/geocode/search?q=${encodeURIComponent(q)}`),
  updateLocation: (photoIds: string[], latitude: number, longitude: number) =>
    request<LocationUpdateResponse>('/api/photos/location', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo_ids: photoIds, latitude, longitude }),
    }),
  // 사진 메모(M5) — upsert + 동기 임베딩. photoId는 canonical(detail.photo_id) 기준.
  putNote: (photoId: string, text: string) =>
    request<NoteResponse>(`/api/photos/${encodeURIComponent(photoId)}/note`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    }),
  deleteNote: (photoId: string) =>
    request<void>(`/api/photos/${encodeURIComponent(photoId)}/note`, { method: 'DELETE' }),
  putNoteByDate: (date: string, text: string) =>
    request<NoteByDateResponse>('/api/photos/note/by-date', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date, text }),
    }),
  thumbUrl: (photoId: string, size: 320 | 1280) =>
    `/api/photos/${encodeURIComponent(photoId)}/thumb?size=${size}`,
  originalUrl: (photoId: string) => `/api/photos/${encodeURIComponent(photoId)}/original`,
}

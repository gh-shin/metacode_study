// zustand 1스토어 — 지도 셸의 모드·선택 날짜·검색 상태·카메라 요청 (prd §6 상태 모델).
// 지도 인스턴스 자체는 스토어에 두지 않는다(MapView 내부 ref) — 스토어는 직렬화
// 가능한 의도(카메라 요청 객체)만 들고, MapView가 seq 변화를 감지해 소비한다.

import { create } from 'zustand'
import type { GeocodeCandidate, NoLocationGroup, SearchResponse } from './api/client'

// 모드 전환 규칙 (M3·M4 확장) —
// · browse → dateDetail(클러스터 시트의 날짜 헤더 탭): 닫기 → browse.
// · browse/search → photoDetail(점·썸네일 마커·하이라이트 점 탭): 닫기 → browse/search.
// · browse → clusterDetail(클러스터 탭): 닫기 → browse. clusterDetail → dateDetail은
//   cluster를 비운다(뒤로가기 없음).
// · 검색 실행(finishSearch) → search(결과 시트): 검색바가 상시라 어느 모드에서든 재검색 가능.
// · search → dateDetail(lane '더보기'·lane 헤더·하이라이트 점 탭): returnTo='search' —
//   닫기 시 search로 복귀(searchResult 보존 = 검색 컨텍스트 유지). dateDetail 안에서
//   다른 마커를 탭해도 returnTo는 유지된다.
// · search → clusterDetail: 검색 컨텍스트 소멸(searchResult 클리어 → 하이라이트 제거,
//   복귀 없음 — 닫기는 항상 browse).
// · 검색 시트 닫기(closeSearch) → browse + searchResult 클리어(MapView가 구독해
//   하이라이트 제거). 시트는 동시에 1개만 뜬다.
// · geocode(M4, 배지 탭): geocodeGroup=null이면 드로어, 선택하면 GeocodeFlow.
//   진입 시 검색 컨텍스트 소멸(클러스터와 동일). 플로우 닫기 → 드로어 복귀,
//   드로어 닫기 → browse. geocode 중 마커·클러스터 탭은 MapView가 무시한다.
export type Mode = 'browse' | 'search' | 'dateDetail' | 'clusterDetail' | 'photoDetail' | 'geocode'

// 수동 지오코딩 대상 좌표 — 후보 탭(candidate 보존 = 모달 주소 미리보기) 또는
// 지도 long-press(candidate=null = "저장 후 주소 자동 조회").
export interface GeocodeTarget {
  latitude: number
  longitude: number
  candidate: GeocodeCandidate | null
}

// 클러스터 leaf — 지도 GeoJSON properties(id·KST 달력일)의 부분집합.
export interface ClusterLeaf {
  id: string
  date: string
}

export interface ClusterSelection {
  leaves: ClusterLeaf[]
  // 클러스터 point_count — leaves가 cap(1,000)으로 잘리면 total > leaves.length.
  total: number
}

// [lng, lat] (MapLibre 규약).
export type LngLat = [number, number]
// [[minLng, minLat], [maxLng, maxLat]].
export type Bounds = [LngLat, LngLat]

// fitBounds 시 가시 영역 패딩(px) — 시트·상단 바가 마커를 가리지 않게 발행처가 지정.
export interface CameraPadding {
  top: number
  bottom: number
  left: number
  right: number
}

export interface CameraRequest {
  type: 'flyTo' | 'fitBounds'
  center?: LngLat
  bounds?: Bounds
  zoom?: number
  padding?: CameraPadding
  seq: number // 단조 증가 — MapView가 마지막 소비 seq와 비교해 1회만 실행한다.
}

interface AppStore {
  mode: Mode
  selectedDate: string | null
  selectedPhotoId: string | null
  cluster: ClusterSelection | null
  cameraRequest: CameraRequest | null
  // 시트 열기마다 증가 — App이 시트 key로 써서 강제 리마운트한다(closing·스크롤
  // 상태가 다음 선택으로 유출되는 것을 차단, cameraRequest.seq와 같은 패턴).
  selectionSeq: number
  // 검색(M3) — searchQuery는 마지막 실행 질의, searchResult는 결과 시트·지도
  // 하이라이트의 단일 원천(null = 하이라이트 없음).
  searchQuery: string
  searchResult: SearchResponse | null
  searching: boolean
  // dateDetail 닫기 복귀처 — search에서 진입했을 때만 'search'.
  returnTo: 'search' | null
  // 위치 미상(M4) — noLocationCount는 배지 표시값(null=미조회·0=숨김),
  // noLocationSeq는 저장 성공 후 배지·드로어 재조회 트리거(단조 증가).
  noLocationCount: number | null
  noLocationSeq: number
  geocodeGroup: NoLocationGroup | null
  // 후보 핀·선택 좌표 — MapView가 전용 source로 그린다(검색 하이라이트 패턴).
  geocodeCandidates: GeocodeCandidate[]
  geocodeTarget: GeocodeTarget | null
  // 위치 지정 후 /api/map/photos 강제 재요청 트리거(단조 증가).
  mapRefreshSeq: number
  // 예시 칩 → SearchBar 트리거 — SearchBar가 effect로 소비 후 null로 정리.
  pendingQuery: string | null

  openDate: (date: string) => void
  closeDate: () => void
  openPhoto: (photoId: string) => void
  closePhoto: () => void
  openCluster: (selection: ClusterSelection) => void
  closeCluster: () => void
  beginSearch: () => void
  finishSearch: (query: string, result: SearchResponse) => void
  failSearch: () => void
  closeSearch: () => void
  setNoLocationCount: (count: number) => void
  bumpNoLocation: () => void
  openGeocode: () => void
  selectGeocodeGroup: (group: NoLocationGroup) => void
  backToGeocodeList: () => void
  closeGeocode: () => void
  setGeocodeCandidates: (candidates: GeocodeCandidate[]) => void
  setGeocodeTarget: (target: GeocodeTarget | null) => void
  // 후보 탭 공통 동작(선택 + flyTo zoom 14) — 시트 리스트와 지도 핀이 공유.
  selectGeocodeCandidate: (candidate: GeocodeCandidate) => void
  refreshMapPhotos: () => void
  flyTo: (center: LngLat, zoom?: number, padding?: CameraPadding) => void
  fitBounds: (bounds: Bounds, padding?: CameraPadding) => void
  setPendingQuery: (q: string) => void
  clearPendingQuery: () => void
}

export const useStore = create<AppStore>((set, get) => ({
  mode: 'browse',
  selectedDate: null,
  selectedPhotoId: null,
  cluster: null,
  cameraRequest: null,
  selectionSeq: 0,
  searchQuery: '',
  searchResult: null,
  searching: false,
  returnTo: null,
  noLocationCount: null,
  noLocationSeq: 0,
  geocodeGroup: null,
  geocodeCandidates: [],
  geocodeTarget: null,
  mapRefreshSeq: 0,
  pendingQuery: null,

  openDate: (date) =>
    set((s) => ({
      mode: 'dateDetail',
      selectedDate: date,
      selectedPhotoId: null,
      cluster: null,
      // search에서 진입하면 닫기 시 복귀, dateDetail 내 재진입(다른 마커 탭)은 유지.
      returnTo: s.mode === 'search' ? 'search' : s.mode === 'dateDetail' ? s.returnTo : null,
      selectionSeq: s.selectionSeq + 1,
    })),
  closeDate: () =>
    set((s) =>
      s.returnTo === 'search' && s.searchResult
        ? { mode: 'search', selectedDate: null, returnTo: null }
        : { mode: 'browse', selectedDate: null, returnTo: null },
    ),
  openPhoto: (photoId) =>
    set((s) => ({
      mode: 'photoDetail',
      selectedPhotoId: photoId,
      selectedDate: null,
      cluster: null,
      returnTo: s.mode === 'search' ? 'search' : s.returnTo === 'search' ? 'search' : null,
      selectionSeq: s.selectionSeq + 1,
    })),
  closePhoto: () =>
    set((s) =>
      s.returnTo === 'search' && s.searchResult
        ? { mode: 'search', selectedPhotoId: null, returnTo: null }
        : { mode: 'browse', selectedPhotoId: null, returnTo: null },
    ),
  // 카메라 요청 없음 — 클러스터 탭은 즉시 표출, 줌은 네이티브 제스처에 위임(피드백 ③).
  // 검색 컨텍스트는 소멸한다(전환 규칙 — 클러스터 탐색으로 의도가 넘어간 것으로 본다).
  openCluster: (selection) =>
    set((s) => ({
      mode: 'clusterDetail',
      cluster: selection,
      selectedDate: null,
      selectedPhotoId: null,
      searchResult: null,
      returnTo: null,
      selectionSeq: s.selectionSeq + 1,
    })),
  closeCluster: () => set({ mode: 'browse', cluster: null }),
  beginSearch: () => set({ searching: true }),
  // 검색바는 상시 노출 — geocode 모드에서 검색하면 지오코딩 흐름도 정리한다.
  finishSearch: (query, result) =>
    set((s) => ({
      mode: 'search',
      searchQuery: query,
      searchResult: result,
      searching: false,
      selectedDate: null,
      selectedPhotoId: null,
      cluster: null,
      returnTo: null,
      geocodeGroup: null,
      geocodeCandidates: [],
      geocodeTarget: null,
      selectionSeq: s.selectionSeq + 1,
    })),
  failSearch: () => set({ searching: false }),
  closeSearch: () =>
    set({ mode: 'browse', searchResult: null, selectedPhotoId: null, returnTo: null }),
  setNoLocationCount: (count) => set({ noLocationCount: count }),
  bumpNoLocation: () => set((s) => ({ noLocationSeq: s.noLocationSeq + 1 })),
  // 배지 탭 → 드로어 — 검색 컨텍스트는 소멸한다(클러스터 전환과 동일 규칙).
  openGeocode: () =>
    set((s) => ({
      mode: 'geocode',
      geocodeGroup: null,
      geocodeCandidates: [],
      geocodeTarget: null,
      selectedDate: null,
      selectedPhotoId: null,
      cluster: null,
      searchResult: null,
      returnTo: null,
      selectionSeq: s.selectionSeq + 1,
    })),
  selectGeocodeGroup: (group) =>
    set((s) => ({
      geocodeGroup: group,
      geocodeCandidates: [],
      geocodeTarget: null,
      selectionSeq: s.selectionSeq + 1,
    })),
  // 저장/취소(플로우 닫기) → 드로어 복귀 — 핀·선택은 함께 정리한다.
  backToGeocodeList: () =>
    set((s) => ({
      geocodeGroup: null,
      geocodeCandidates: [],
      geocodeTarget: null,
      selectionSeq: s.selectionSeq + 1,
    })),
  closeGeocode: () =>
    set({ mode: 'browse', geocodeGroup: null, geocodeCandidates: [], geocodeTarget: null }),
  setGeocodeCandidates: (candidates) => set({ geocodeCandidates: candidates }),
  setGeocodeTarget: (target) => set({ geocodeTarget: target }),
  selectGeocodeCandidate: (candidate) =>
    set((s) => ({
      geocodeTarget: {
        latitude: candidate.latitude,
        longitude: candidate.longitude,
        candidate,
      },
      cameraRequest: {
        type: 'flyTo',
        center: [candidate.longitude, candidate.latitude],
        zoom: 14,
        seq: (s.cameraRequest?.seq ?? 0) + 1,
      },
    })),
  refreshMapPhotos: () => set((s) => ({ mapRefreshSeq: s.mapRefreshSeq + 1 })),
  setPendingQuery: (q) => set({ pendingQuery: q }),
  clearPendingQuery: () => set({ pendingQuery: null }),
  flyTo: (center, zoom, padding) =>
    set({
      cameraRequest: { type: 'flyTo', center, zoom, padding, seq: nextSeq(get) },
    }),
  fitBounds: (bounds, padding) =>
    set({
      cameraRequest: { type: 'fitBounds', bounds, padding, seq: nextSeq(get) },
    }),
}))

function nextSeq(get: () => AppStore): number {
  return (get().cameraRequest?.seq ?? 0) + 1
}

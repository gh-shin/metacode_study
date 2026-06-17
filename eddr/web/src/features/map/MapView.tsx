import { useEffect, useRef } from 'react'
import type { RefObject } from 'react'
import maplibregl from 'maplibre-gl'
import type { GeoJSONSource, LngLatBoundsLike, PointLike } from 'maplibre-gl'
import { api } from '../../api/client'
import type { GeocodeCandidate, MapPhotosResponse, SearchResponse } from '../../api/client'
import { useStore } from '../../store'
import type { CameraRequest, ClusterLeaf, GeocodeTarget } from '../../store'
import { useLongPress } from './useLongPress'

// OpenFreeMap liberty — 키 불필요·무료(ADR-0009 §5).
const STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty'
const SOURCE_ID = 'photos'
// 검색 결과 하이라이트(M3) — 클러스터 source와 분리해 강조색 큰 점으로 겹쳐 그린다.
const HIGHLIGHT_SOURCE_ID = 'search-highlight'
const HIGHLIGHT_CAP = 50
const HIGHLIGHT_COLOR = '#f97316' // 클러스터 blue 계열과 구분되는 주황.
// 수동 지오코딩 핀(M4) — 후보·선택 좌표 전용 source(검색 하이라이트 패턴).
const GEOCODE_SOURCE_ID = 'geocode-pins'
const GEOCODE_PIN_COLOR = '#ef4444' // 빨간 느낌표 배지와 같은 계열.
const GEOCODE_PIN_SELECTED_RING = '#fbbf24' // 선택 핀 강조 링.
// 고줌에서만 HTML 썸네일 마커를 띄운다 — 그 미만은 클러스터/점만(성능).
const THUMB_ZOOM = 14
const THUMB_MARKER_CAP = 60
// 클러스터 시트 leaves 상한 — 초과분은 헤더에 "(상위 1,000장)"으로만 알린다.
const LEAVES_CAP = 1000
// 팬 1회당 주변 썸네일 prefetch 상한(피드백 ①).
const PREFETCH_CAP = 60
// 초기 뷰 — 현위치/폴백 카메라가 곧 덮어쓴다(서울 근방 기본값).
const INITIAL_CENTER: [number, number] = [127.0, 37.5]
const INITIAL_ZOOM = 6
// accent 계열 3단계(라이트→딥) — 클러스터 크기 step과 짝.
const CLUSTER_COLORS = ['#60a5fa', '#3b82f6', '#1d4ed8']

// GeoJSON 일괄(raw ~1MB)은 initLayers와 현위치 폴백이 함께 쓴다 — 모듈 레벨에서
// promise 1회 캐시해 이중 fetch를 막는다(모바일 페이로드 절약, code-review 중간-1).
// 실패는 캐시하지 않는다 — 일시 네트워크 오류가 영구 빈 지도가 되지 않게.
let mapPhotosPromise: Promise<MapPhotosResponse> | null = null
function fetchMapPhotosCached(): Promise<MapPhotosResponse> {
  if (!mapPhotosPromise) {
    mapPhotosPromise = api.mapPhotos().catch((err: unknown) => {
      mapPhotosPromise = null
      throw err
    })
  }
  return mapPhotosPromise
}

export function MapView() {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const thumbMarkersRef = useRef<Map<string, maplibregl.Marker>>(new Map())
  const geoMarkerRef = useRef<maplibregl.Marker | null>(null)
  const didLocateRef = useRef(false)
  // 모듈 전역 store의 마지막 cameraRequest seq로 초기화 — remount(HMR) 시 과거
  // 요청 재적용(카메라 점프)을 막는다(code-review 낮음-6).
  const consumedSeqRef = useRef(useStore.getState().cameraRequest?.seq ?? 0)
  // 세션 내 prefetch 완료(또는 마커로 요청된) photo_id — 중복 prefetch 방지.
  const prefetchedRef = useRef<Set<string>>(new Set())
  const openDate = useStore((s) => s.openDate)
  const openCluster = useStore((s) => s.openCluster)

  // 지도 1회 생성 — openDate는 zustand 액션이라 참조 불변(effect 재실행 없음).
  useEffect(() => {
    if (!containerRef.current) return
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE_URL,
      center: INITIAL_CENTER,
      zoom: INITIAL_ZOOM,
      attributionControl: { compact: true },
    })
    mapRef.current = map
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

    map.on('load', () => {
      void initLayers(map)
    })
    const refresh = () => {
      syncThumbMarkers(map, thumbMarkersRef, openDate)
      prefetchNearbyThumbs(map, prefetchedRef.current, thumbMarkersRef.current)
    }
    map.on('idle', refresh)
    map.on('moveend', refresh)

    return () => {
      thumbMarkersRef.current.forEach((m) => m.remove())
      thumbMarkersRef.current.clear()
      geoMarkerRef.current?.remove()
      geoMarkerRef.current = null
      map.remove()
      mapRef.current = null
    }
  }, [openDate])

  // 검색 하이라이트 동기화 — searchResult가 단일 원천: null이면 제거(closeSearch·
  // openCluster), 갱신이면 교체. source가 아직 없으면(스타일 로딩 중) initLayers가
  // 생성 시점에 현재 store 상태를 읽어 반영하므로 여기선 건너뛴다.
  const searchResult = useStore((s) => s.searchResult)
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const source = map.getSource(HIGHLIGHT_SOURCE_ID) as GeoJSONSource | undefined
    if (source) source.setData(highlightCollection(searchResult))
  }, [searchResult])

  // 지오코드 핀 동기화(M4) — geocode 모드에서만 그린다. source 미생성(스타일
  // 로딩 중)이면 initLayers가 생성 시점의 store 상태를 읽으므로 건너뛴다.
  const mode = useStore((s) => s.mode)
  const geocodeCandidates = useStore((s) => s.geocodeCandidates)
  const geocodeTarget = useStore((s) => s.geocodeTarget)
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const source = map.getSource(GEOCODE_SOURCE_ID) as GeoJSONSource | undefined
    if (source) {
      source.setData(
        geocodePinCollection(
          mode === 'geocode' ? geocodeCandidates : [],
          mode === 'geocode' ? geocodeTarget : null,
        ),
      )
    }
  }, [mode, geocodeCandidates, geocodeTarget])

  // 위치 지정 직후(M4) — 모듈 promise 캐시와 HTTP 캐시(max-age=300)를 모두
  // 우회해 GeoJSON을 다시 받아 새 마커를 띄운다(prd §6-b 강제 재요청).
  const mapRefreshSeq = useStore((s) => s.mapRefreshSeq)
  useEffect(() => {
    if (mapRefreshSeq === 0) return
    const map = mapRef.current
    if (!map) return
    api
      .mapPhotos(true)
      .then((data) => {
        mapPhotosPromise = Promise.resolve(data) // 이후 소비자도 새 데이터를 보게.
        const source = map.getSource(SOURCE_ID) as GeoJSONSource | undefined
        if (source) source.setData(data)
      })
      .catch(() => undefined)
  }, [mapRefreshSeq])

  // long-press(M4) — GeocodeFlow(그룹 선택됨)일 때만 활성. 지도 아무 곳이나
  // 650ms 누르면 그 좌표를 선택한다 — 후보 0건 경로의 항시 출구.
  const geocodeFlowActive = useStore((s) => s.mode === 'geocode' && s.geocodeGroup !== null)
  useLongPress(
    containerRef,
    (clientX, clientY) => {
      const map = mapRef.current
      if (!map) return
      const rect = map.getContainer().getBoundingClientRect()
      const point = map.unproject([clientX - rect.left, clientY - rect.top])
      useStore.getState().setGeocodeTarget({
        latitude: point.lat,
        longitude: point.lng,
        candidate: null,
      })
    },
    geocodeFlowActive,
  )

  // 마커 탭 — 점(12px)을 정확히 맞추기 어려운 모바일을 위해 탭 지점 ±22px
  // bbox로 히트 판정(터치 표적 ~44px). 겹치면 위에 그려진 feature(점) 우선 —
  // 하이라이트 점이 최상단이라 검색 결과 탭이 이긴다(→ 그 날짜 dateDetail,
  // search 모드에서 진입하므로 returnTo='search'). 클러스터 = leaves 즉시 표출
  // (ClusterSheet, 카메라 이동 없음 — 피드백 ③), 비클러스터 점 = 날짜 상세 진입.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const onMapClick = (e: maplibregl.MapMouseEvent) => {
      const pad = 22
      const bbox: [PointLike, PointLike] = [
        [e.point.x - pad, e.point.y - pad],
        [e.point.x + pad, e.point.y + pad],
      ]
      // geocode 모드(M4): 후보 핀 탭(±22px = 표적 ~44px)만 처리 — 클러스터·
      // 점 탭은 무시해 위치 지정 흐름이 다른 시트로 이탈하지 않게 한다.
      if (useStore.getState().mode === 'geocode') {
        const layers = ['geocode-pin-selected', 'geocode-pins'].filter((id) => map.getLayer(id))
        if (layers.length === 0) return
        const feature = map.queryRenderedFeatures(bbox, { layers })[0]
        const index = feature?.properties?.index
        const candidate =
          typeof index === 'number' ? useStore.getState().geocodeCandidates[index] : undefined
        if (candidate) useStore.getState().selectGeocodeCandidate(candidate)
        return
      }
      if (!map.getLayer('unclustered')) return
      const feature = map.queryRenderedFeatures(bbox, {
        layers: ['search-highlight', 'clusters', 'unclustered'].filter((id) => map.getLayer(id)),
      })[0]
      if (!feature || feature.geometry.type !== 'Point') return
      const clusterId = feature.properties?.cluster_id
      if (clusterId != null) {
        const total = (feature.properties?.point_count as number | undefined) ?? 0
        const source = map.getSource(SOURCE_ID) as GeoJSONSource
        source
          .getClusterLeaves(clusterId, LEAVES_CAP, 0)
          .then((leaves) => {
            const items: ClusterLeaf[] = []
            for (const leaf of leaves) {
              const id = leaf.properties?.id
              const date = leaf.properties?.date
              if (typeof id === 'string' && typeof date === 'string') items.push({ id, date })
            }
            if (items.length > 0)
              openCluster({ leaves: items, total: Math.max(total, items.length) })
          })
          .catch(() => undefined)
      } else if (typeof feature.properties?.date === 'string' && feature.properties.date) {
        // 빈 date('') 가드 — 촬영 시각 미상 하이라이트 점은 날짜 상세가 없다.
        openDate(feature.properties.date)
      }
    }
    const enter = () => (map.getCanvas().style.cursor = 'pointer')
    const leave = () => (map.getCanvas().style.cursor = '')
    map.on('click', onMapClick)
    for (const layer of ['clusters', 'unclustered']) {
      map.on('mouseenter', layer, enter)
      map.on('mouseleave', layer, leave)
    }
    return () => {
      map.off('click', onMapClick)
      for (const layer of ['clusters', 'unclustered']) {
        map.off('mouseenter', layer, enter)
        map.off('mouseleave', layer, leave)
      }
    }
  }, [openDate, openCluster])

  // cameraRequest 소비 — seq가 바뀐 요청만 1회 실행한다(store는 인스턴스를 모름).
  useEffect(() => {
    const unsub = useStore.subscribe((state) => {
      const req = state.cameraRequest
      const map = mapRef.current
      if (!req || !map || req.seq === consumedSeqRef.current) return
      consumedSeqRef.current = req.seq
      applyCamera(map, req)
    })
    return unsub
  }, [])

  // 현위치 watch — secure context(HTTPS)에서만 동작, 실패 시 최신 사진 위치 폴백.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !('geolocation' in navigator)) {
      fallbackToLatest()
      return
    }
    const watchId = navigator.geolocation.watchPosition(
      (pos) => {
        const center: [number, number] = [pos.coords.longitude, pos.coords.latitude]
        if (!geoMarkerRef.current) {
          geoMarkerRef.current = new maplibregl.Marker({ element: buildGeoDot() })
            .setLngLat(center)
            .addTo(map)
        } else {
          geoMarkerRef.current.setLngLat(center)
        }
        if (!didLocateRef.current) {
          didLocateRef.current = true
          map.flyTo({ center, zoom: 13 })
        }
      },
      (err) => {
        console.warn('geolocation unavailable — 최근 사진 위치로 폴백:', err.message)
        if (!didLocateRef.current) fallbackToLatest()
      },
      { enableHighAccuracy: true, maximumAge: 30000, timeout: 10000 },
    )
    return () => navigator.geolocation.clearWatch(watchId)
  }, [])

  // 폴백: GeoJSON 중 최신 date feature 위치로 이동(콘솔 경고만, UI 에러 없음).
  function fallbackToLatest() {
    if (didLocateRef.current) return
    fetchMapPhotosCached()
      .then((fc) => {
        if (didLocateRef.current || fc.features.length === 0) return
        const latest = fc.features.reduce((a, b) =>
          (b.properties.date ?? '') > (a.properties.date ?? '') ? b : a,
        )
        const map = mapRef.current
        if (!map) return
        didLocateRef.current = true
        map.flyTo({ center: latest.geometry.coordinates, zoom: 11 })
      })
      .catch(() => undefined)
  }

  return <div className="map" ref={containerRef} />
}

async function initLayers(map: maplibregl.Map) {
  const data = await fetchMapPhotosCached().catch(() => null)
  if (!data || map.getSource(SOURCE_ID)) return
  map.addSource(SOURCE_ID, {
    type: 'geojson',
    data,
    cluster: true,
    clusterRadius: 48,
    clusterMaxZoom: 15,
  })
  map.addLayer({
    id: 'clusters',
    type: 'circle',
    source: SOURCE_ID,
    filter: ['has', 'point_count'],
    paint: {
      'circle-color': [
        'step',
        ['get', 'point_count'],
        CLUSTER_COLORS[0],
        25,
        CLUSTER_COLORS[1],
        100,
        CLUSTER_COLORS[2],
      ],
      'circle-radius': ['step', ['get', 'point_count'], 16, 25, 22, 100, 30],
      'circle-opacity': 0.85,
      'circle-stroke-width': 2,
      'circle-stroke-color': '#ffffff',
    },
  })
  map.addLayer({
    id: 'cluster-count',
    type: 'symbol',
    source: SOURCE_ID,
    filter: ['has', 'point_count'],
    layout: {
      'text-field': '{point_count_abbreviated}',
      'text-font': ['Noto Sans Regular'],
      'text-size': 12,
    },
    paint: { 'text-color': '#ffffff' },
  })
  map.addLayer({
    id: 'unclustered',
    type: 'circle',
    source: SOURCE_ID,
    filter: ['!', ['has', 'point_count']],
    paint: {
      'circle-color': CLUSTER_COLORS[1],
      'circle-radius': 6,
      'circle-stroke-width': 2,
      'circle-stroke-color': '#ffffff',
    },
  })
  // 검색 하이라이트 — 별도 source + 최상단 layer(강조색 큰 점, 클러스터와 구분).
  // 생성 시점의 store 상태를 읽는다 — 스타일 로드 전에 도착한 검색 결과도 반영.
  map.addSource(HIGHLIGHT_SOURCE_ID, {
    type: 'geojson',
    data: highlightCollection(useStore.getState().searchResult),
  })
  map.addLayer({
    id: 'search-highlight',
    type: 'circle',
    source: HIGHLIGHT_SOURCE_ID,
    paint: {
      'circle-color': HIGHLIGHT_COLOR,
      'circle-radius': 9,
      'circle-stroke-width': 3,
      'circle-stroke-color': '#ffffff',
    },
  })
  // 지오코드 핀(M4) — 후보/선택 2 layer. 생성 시점의 store 상태를 읽는다.
  const state = useStore.getState()
  map.addSource(GEOCODE_SOURCE_ID, {
    type: 'geojson',
    data: geocodePinCollection(
      state.mode === 'geocode' ? state.geocodeCandidates : [],
      state.mode === 'geocode' ? state.geocodeTarget : null,
    ),
  })
  map.addLayer({
    id: 'geocode-pins',
    type: 'circle',
    source: GEOCODE_SOURCE_ID,
    filter: ['!', ['get', 'selected']],
    paint: {
      'circle-color': GEOCODE_PIN_COLOR,
      'circle-radius': 11,
      'circle-stroke-width': 3,
      'circle-stroke-color': '#ffffff',
    },
  })
  map.addLayer({
    id: 'geocode-pin-selected',
    type: 'circle',
    source: GEOCODE_SOURCE_ID,
    filter: ['get', 'selected'],
    paint: {
      'circle-color': GEOCODE_PIN_COLOR,
      'circle-radius': 13,
      'circle-stroke-width': 4,
      'circle-stroke-color': GEOCODE_PIN_SELECTED_RING,
    },
  })
}

// 검색 결과 중 GPS 사진(≤50)을 하이라이트 FeatureCollection으로 — properties는
// 기존 photos source와 동형(id·date). 날짜 미상은 date=''(탭 시 무동작 가드).
function highlightCollection(result: SearchResponse | null): MapPhotosResponse {
  const features: MapPhotosResponse['features'] = []
  if (result) {
    for (const group of result.groups) {
      for (const photo of group.photos) {
        if (features.length >= HIGHLIGHT_CAP) break
        if (photo.latitude === null || photo.longitude === null) continue
        features.push({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [photo.longitude, photo.latitude] },
          properties: { id: photo.photo_id, date: group.date ?? '' },
        })
      }
    }
  }
  return { type: 'FeatureCollection', features }
}

// 지오코드 핀 FeatureCollection — 후보는 index 보존(탭 시 역참조), 선택 좌표는
// selected 강조 feature로 추가한다(후보 탭이면 같은 위치에 겹쳐 그려져 강조,
// long-press면 후보 밖 단독 핀). index=-1(선택 전용)은 탭 시 무동작.
interface GeocodePinCollection {
  type: 'FeatureCollection'
  features: {
    type: 'Feature'
    geometry: { type: 'Point'; coordinates: [number, number] }
    properties: { index: number; selected: boolean }
  }[]
}

function geocodePinCollection(
  candidates: GeocodeCandidate[],
  target: GeocodeTarget | null,
): GeocodePinCollection {
  const features: GeocodePinCollection['features'] = candidates.map((candidate, index) => ({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [candidate.longitude, candidate.latitude] },
    properties: { index, selected: false },
  }))
  if (target) {
    features.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [target.longitude, target.latitude] },
      properties: { index: -1, selected: true },
    })
  }
  return { type: 'FeatureCollection', features }
}

// 고줌일 때 화면 내 비클러스터 점을 HTML 썸네일 마커로 — 상한 60.
// id 기준 diff(유지·추가·제거)로 동기화 — 팬·줌마다 풀 재생성하면 마커가
// 일제히 깜빡이므로, 계속 보이는 마커는 DOM을 그대로 둔다.
function syncThumbMarkers(
  map: maplibregl.Map,
  poolRef: RefObject<Map<string, maplibregl.Marker>>,
  openDate: (date: string) => void,
) {
  const pool = poolRef.current
  if (map.getZoom() < THUMB_ZOOM || !map.getLayer('unclustered')) {
    pool.forEach((m) => m.remove())
    pool.clear()
    return
  }
  const features = map.queryRenderedFeatures({ layers: ['unclustered'] })
  const keep = new Set<string>()
  for (const feature of features) {
    if (keep.size >= THUMB_MARKER_CAP) break
    const id = feature.properties?.id as string | undefined
    const date = feature.properties?.date as string | undefined
    const geom = feature.geometry
    if (!id || keep.has(id) || geom.type !== 'Point') continue
    keep.add(id)
    if (pool.has(id)) continue // 이미 떠 있는 마커 — 그대로 유지.
    const el = buildThumbMarker(id, () => {
      // geocode 모드 중 시트 전환 금지 — 위치 지정 흐름을 보존한다(M4).
      if (useStore.getState().mode === 'geocode') return
      if (typeof date === 'string') openDate(date)
    })
    pool.set(
      id,
      new maplibregl.Marker({ element: el })
        .setLngLat(geom.coordinates as [number, number])
        .addTo(map),
    )
  }
  for (const [id, marker] of pool) {
    if (!keep.has(id)) {
      marker.remove()
      pool.delete(id)
    }
  }
}

function buildThumbMarker(photoId: string, onTap: () => void): HTMLElement {
  const el = document.createElement('button')
  el.type = 'button'
  el.className = 'thumb-marker'
  el.setAttribute('aria-label', '이 사진의 날짜 보기')
  const img = document.createElement('img')
  img.decoding = 'async'
  img.loading = 'lazy'
  img.alt = ''
  // 로드 전엔 버튼의 서피스 원이 placeholder — onload에 120ms fade-in(피드백 ①).
  img.addEventListener('load', () => img.classList.add('loaded'), { once: true })
  img.src = api.thumbUrl(photoId, 320)
  el.appendChild(img)
  el.addEventListener('click', (e) => {
    e.stopPropagation()
    onTap()
  })
  return el
}

// Safari는 requestIdleCallback 미지원 — setTimeout 폴백(피드백 ①, iPhone 대상).
const scheduleIdle: (cb: () => void) => void =
  typeof requestIdleCallback === 'function'
    ? (cb) => requestIdleCallback(cb, { timeout: 2000 })
    : (cb) => window.setTimeout(cb, 200)

// 뷰포트 1.5배 버퍼 안의 비클러스터 점 썸네일을 유휴 시간에 미리 받는다 —
// 팬 직후 마커가 즉시 차 보이게(피드백 ①). 서버 Cache-Control(1일)과 합으로
// HTTP 캐시를 데우는 방식이라 마커 생성 경로(buildThumbMarker)는 그대로다.
function prefetchNearbyThumbs(
  map: maplibregl.Map,
  prefetched: Set<string>,
  pool: Map<string, maplibregl.Marker>,
) {
  if (map.getZoom() < THUMB_ZOOM || !map.getLayer('unclustered')) return
  const bounds = map.getBounds()
  // 1.5배 박스 = 각 변 25% 확장.
  const padLng = (bounds.getEast() - bounds.getWest()) * 0.25
  const padLat = (bounds.getNorth() - bounds.getSouth()) * 0.25
  // querySourceFeatures는 로드된 타일 전체(뷰포트+버퍼)를 보며 타일 경계에서
  // 같은 feature가 중복될 수 있다 — prefetched/pool로 dedupe.
  const features = map.querySourceFeatures(SOURCE_ID, {
    filter: ['!', ['has', 'point_count']],
  })
  const ids: string[] = []
  for (const feature of features) {
    if (ids.length >= PREFETCH_CAP) break
    const id = feature.properties?.id as string | undefined
    const geom = feature.geometry
    if (!id || prefetched.has(id) || pool.has(id) || geom.type !== 'Point') continue
    const [lng, lat] = geom.coordinates as [number, number]
    if (
      lng < bounds.getWest() - padLng ||
      lng > bounds.getEast() + padLng ||
      lat < bounds.getSouth() - padLat ||
      lat > bounds.getNorth() + padLat
    )
      continue
    prefetched.add(id)
    ids.push(id)
  }
  if (ids.length === 0) return
  scheduleIdle(() => {
    for (const id of ids) {
      const img = new Image()
      img.decoding = 'async'
      img.src = api.thumbUrl(id, 320)
    }
  })
}

function buildGeoDot(): HTMLElement {
  const el = document.createElement('div')
  el.className = 'geo-dot'
  return el
}

function applyCamera(map: maplibregl.Map, req: CameraRequest) {
  if (req.type === 'flyTo' && req.center) {
    map.flyTo({ center: req.center, zoom: req.zoom })
  } else if (req.type === 'fitBounds' && req.bounds) {
    try {
      map.fitBounds(req.bounds as LngLatBoundsLike, {
        padding: req.padding ?? 80,
        maxZoom: 15,
        duration: 600,
      })
    } catch {
      // padding 합이 캔버스보다 큰 극단 뷰포트 — 카메라 유지가 안전하다.
    }
  }
}

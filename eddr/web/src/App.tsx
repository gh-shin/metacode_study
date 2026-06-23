import { useEffect, useState } from 'react'
import { api } from './api/client'
import type { StatusResponse } from './api/client'
import { GeocodeFlow } from './features/geocode/GeocodeFlow'
import { NoLocationBadge } from './features/geocode/NoLocationBadge'
import { NoLocationDrawer } from './features/geocode/NoLocationDrawer'
import { MapView } from './features/map/MapView'
import { ClusterSheet } from './features/photos/ClusterSheet'
import { DateDetailSheet } from './features/photos/DateDetailSheet'
import { PhotoDetailView } from './features/photos/PhotoDetailView'
import { Sheet } from './features/photos/Sheet'
import { EmptyState } from './features/search/EmptyState'
import { ResultsSheet } from './features/search/ResultsSheet'
import { SearchBar } from './features/search/SearchBar'
import { StatusSheet } from './features/status/StatusSheet'
import { useStore } from './store'

export default function App() {
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [showStatus, setShowStatus] = useState(false)
  const mode = useStore((s) => s.mode)
  const selectedDate = useStore((s) => s.selectedDate)
  const selectedPhotoId = useStore((s) => s.selectedPhotoId)
  const cluster = useStore((s) => s.cluster)
  const searchResult = useStore((s) => s.searchResult)
  const geocodeGroup = useStore((s) => s.geocodeGroup)
  const selectionSeq = useStore((s) => s.selectionSeq)
  const closePhoto = useStore((s) => s.closePhoto)

  useEffect(() => {
    api
      .status()
      .then(setStatus)
      .catch(() => setStatus(null))
  }, [])

  return (
    <div className="app">
      <MapView />
      <header className="topbar floating">
        <div className="topbar-side">
          {status && (
            <button
              type="button"
              className="badge"
              onClick={() => setShowStatus(true)}
              aria-label={`${status.ready.toLocaleString()} 검색 가능 — 상태 보기`}
            >
              {status.ready.toLocaleString()} 검색 가능
              {status.path_health.healthy ? '' : ' · ⚠️ 경로 확인'}
            </button>
          )}
          {/* 빨간 느낌표 — 위치 미상 그룹 수(S4 진입점), 0이면 자체 숨김. */}
          <NoLocationBadge />
        </div>
      </header>
      {/* 시트는 모드당 1개 — 전환 규칙은 store.ts Mode 주석 참조.
          key=selectionSeq: 열기마다 리마운트 — closing·스크롤 상태 유출 차단(품질 리뷰). */}
      {mode === 'search' && searchResult && (
        <ResultsSheet key={selectionSeq} result={searchResult} />
      )}
      {mode === 'dateDetail' && selectedDate && (
        <DateDetailSheet key={selectionSeq} date={selectedDate} />
      )}
      {mode === 'clusterDetail' && cluster && (
        <ClusterSheet key={selectionSeq} cluster={cluster} />
      )}
      {mode === 'photoDetail' && selectedPhotoId && (
        <Sheet
          key={selectionSeq}
          ariaLabel="사진 상세"
          onClosed={closePhoto}
          expandable
          overlay={
            <PhotoDetailView
              photoIds={[selectedPhotoId]}
              index={0}
              onClose={closePhoto}
              onNavigate={() => undefined}
            />
          }
          headerContent={
            <div>
              <strong>사진 상세</strong>
            </div>
          }
        >
          <></>
        </Sheet>
      )}
      {/* geocode(M4): 그룹 미선택 = 드로어, 선택 = 장소 검색 패널(GeocodeFlow). */}
      {mode === 'geocode' && !geocodeGroup && <NoLocationDrawer key={selectionSeq} />}
      {mode === 'geocode' && geocodeGroup && (
        <GeocodeFlow key={selectionSeq} group={geocodeGroup} />
      )}
      {/* 상태 시트 — store 모드와 무관한 독립 정보 오버레이. */}
      {showStatus && status && (
        <StatusSheet status={status} onClose={() => setShowStatus(false)} />
      )}
      {/* 빈상태 안내 — 검색 전 홈에서만 표출(지도를 가리지 않게 floating 카드). */}
      {mode === 'browse' && !searchResult && <EmptyState />}
      {/* 검색바 상시 — 시트보다 위(z-index)라 어디서든 재검색 가능. */}
      <SearchBar />
    </div>
  )
}

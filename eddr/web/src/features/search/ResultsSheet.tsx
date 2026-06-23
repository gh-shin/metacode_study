import { useRef, useState } from 'react'
import type { SearchInterpretation, SearchResponse, TripSummary } from '../../api/client'
import { useStore } from '../../store'
import { PhotoDetailView } from '../photos/PhotoDetailView'
import { Sheet } from '../photos/Sheet'
import { ResultLanes } from './ResultLanes'

// 검색 결과 시트 — 헤더에 "N장 · M일" + 해석 칩 줄(오해석 즉시 인지, scenario v2 S2),
// 본문은 관련도순 날짜 lane. 닫으면 browse 복귀 + 결과·하이라이트 클리어(closeSearch).
export function ResultsSheet({ result }: { result: SearchResponse }) {
  const closeSearch = useStore((s) => s.closeSearch)
  const searchQuery = useStore((s) => s.searchQuery)
  // 상세 뷰 컨텍스트는 탭한 lane의 사진 목록 — 시트 전체가 아니다(ClusterSheet 동형).
  const [lightbox, setLightbox] = useState<{ ids: string[]; index: number } | null>(null)

  const dayCount = result.groups.filter((group) => group.date !== null).length
  const showTripSummary =
    result.interpretation.answer_type === 'fact' && result.trip_summary.length > 0

  return (
    <Sheet
      ariaLabel={`"${searchQuery}" 검색 결과`}
      onClosed={closeSearch}
      expandable
      overlay={
        lightbox && (
          <PhotoDetailView
            photoIds={lightbox.ids}
            index={lightbox.index}
            onClose={() => setLightbox(null)}
            onNavigate={(index) => setLightbox({ ids: lightbox.ids, index })}
          />
        )
      }
      headerContent={
        <div className="results-head">
          <div className="results-title">
            <strong>
              검색 결과 {result.total}장 · {dayCount}일
            </strong>
          </div>
          <InterpretationChips interpretation={result.interpretation} />
        </div>
      }
    >
      {result.total === 0 && <p className="sheet-empty">조건에 맞는 사진이 없습니다.</p>}
      {showTripSummary && <TripSummaryCards trips={result.trip_summary} />}
      <ResultLanes groups={result.groups} onOpen={(ids, index) => setLightbox({ ids, index })} />
    </Sheet>
  )
}

function TripSummaryCards({ trips }: { trips: TripSummary[] }) {
  return (
    <section className="trip-summary" aria-label="여행 요약">
      {trips.map((trip) => {
        const dateRange = formatDateRange(utcToKstDate(trip.start_at), utcToKstDate(trip.end_at))
        return (
          <article key={trip.trip_id} className="trip-summary-card">
            <strong>{trip.name}</strong>
            {dateRange && <span>{dateRange}</span>}
            <small>
              {trip.photo_count}장
              {trip.country_codes.length > 0 && ` · ${trip.country_codes.join(', ')}`}
            </small>
          </article>
        )
      })}
    </section>
  )
}

const LONG_PRESS_MS = 650
const MOVE_TOLERANCE_PX = 8
const TRIP_DATE_FORMATTER = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Seoul',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

// 해석 칩 줄 — countries·cities 그대로, 날짜범위, keywords는 한국어(ko) 기본 표시.
// fallback=true(추출 실패 → 임베딩-only)면 경고 배지를 맨 앞에 둔다.
// 칩 줄 길게 누르기(터치 650ms) 또는 데스크톱 우클릭 → 영어/한국어 토글.
function InterpretationChips({ interpretation }: { interpretation: SearchInterpretation }) {
  const [showEn, setShowEn] = useState(false)
  const dateChip = formatDateRange(interpretation.date_from, interpretation.date_to)

  // keywords_ko가 비어 있으면 영어 폴백
  const hasKo = interpretation.keywords_ko.length > 0
  const displayKeywords = showEn || !hasKo ? interpretation.keywords_en : interpretation.keywords_ko

  // 칩 줄 전용 경량 long-press 핸들러 — ref로 관리해 리렌더 간 타이머 참조 보존
  const pressTimer = useRef<number | null>(null)
  const pressStart = useRef({ x: 0, y: 0 })

  const cancelPress = () => {
    if (pressTimer.current !== null) {
      window.clearTimeout(pressTimer.current)
      pressTimer.current = null
    }
  }

  const handlePointerDown = (e: React.PointerEvent) => {
    if (!e.isPrimary) {
      cancelPress()
      return
    }
    pressStart.current = { x: e.clientX, y: e.clientY }
    cancelPress()
    pressTimer.current = window.setTimeout(() => {
      pressTimer.current = null
      setShowEn((v) => !v)
    }, LONG_PRESS_MS)
  }

  const handlePointerMove = (e: React.PointerEvent) => {
    if (pressTimer.current === null || !e.isPrimary) return
    const { x, y } = pressStart.current
    if (Math.hypot(e.clientX - x, e.clientY - y) > MOVE_TOLERANCE_PX) {
      cancelPress()
    }
  }

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault()
    cancelPress()
    setShowEn((v) => !v)
  }

  const ariaLabel = showEn ? '질의 해석 (영어 표시 중, 길게 눌러 한국어로)' : '질의 해석 (길게 눌러 영어 보기)'

  return (
    <div
      className="chips"
      aria-label={ariaLabel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={cancelPress}
      onPointerCancel={cancelPress}
      onContextMenu={handleContextMenu}
    >
      {interpretation.fallback && <span className="chip chip-warn">⚠️ 단순 의미 검색</span>}
      {interpretation.countries.map((name) => (
        <span key={`country-${name}`} className="chip">
          {name}
        </span>
      ))}
      {interpretation.cities.map((name) => (
        <span key={`city-${name}`} className="chip">
          {name}
        </span>
      ))}
      {dateChip && <span className="chip">{dateChip}</span>}
      {displayKeywords.map((keyword) => (
        <span key={`kw-${keyword}`} className="chip chip-muted">
          {keyword}
        </span>
      ))}
    </div>
  )
}

function formatDateRange(from: string | null, to: string | null): string | null {
  if (!from && !to) return null
  return `${from ?? ''}~${to ?? ''}`
}

function utcToKstDate(value: string): string {
  const normalized = value.includes('T') ? value : value.replace(' ', 'T')
  const date = new Date(`${normalized}Z`)
  return Number.isNaN(date.getTime()) ? value.slice(0, 10) : TRIP_DATE_FORMATTER.format(date)
}

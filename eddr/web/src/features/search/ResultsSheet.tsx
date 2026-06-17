import { useRef, useState } from 'react'
import type { SearchInterpretation, SearchResponse } from '../../api/client'
import { useStore } from '../../store'
import { Lightbox } from '../photos/Lightbox'
import { Sheet } from '../photos/Sheet'
import { ResultLanes } from './ResultLanes'

// 검색 결과 시트 — 헤더에 "N장 · M일" + 해석 칩 줄(오해석 즉시 인지, scenario v2 S2),
// 본문은 관련도순 날짜 lane. 닫으면 browse 복귀 + 결과·하이라이트 클리어(closeSearch).
export function ResultsSheet({ result }: { result: SearchResponse }) {
  const closeSearch = useStore((s) => s.closeSearch)
  const searchQuery = useStore((s) => s.searchQuery)
  // 라이트박스 컨텍스트는 탭한 lane의 사진 목록 — 시트 전체가 아니다(ClusterSheet 동형).
  const [lightbox, setLightbox] = useState<{ ids: string[]; index: number } | null>(null)

  const dayCount = result.groups.filter((group) => group.date !== null).length

  return (
    <>
      <Sheet
        ariaLabel={`"${searchQuery}" 검색 결과`}
        onClosed={closeSearch}
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
        <ResultLanes
          groups={result.groups}
          onOpen={(ids, index) => setLightbox({ ids, index })}
        />
      </Sheet>
      {/* 시트 밖 형제로 렌더 — 드래그 중 시트의 inline transform 영향 회피. */}
      {lightbox && (
        <Lightbox
          photoIds={lightbox.ids}
          index={lightbox.index}
          onClose={() => setLightbox(null)}
          onNavigate={(index) => setLightbox({ ids: lightbox.ids, index })}
        />
      )}
    </>
  )
}

const LONG_PRESS_MS = 650
const MOVE_TOLERANCE_PX = 8

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

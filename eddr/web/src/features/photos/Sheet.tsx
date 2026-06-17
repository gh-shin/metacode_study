import { useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent, ReactNode } from 'react'

// 드래그 dismiss 판정 — 이동 >120px 또는 종속도(release velocity) >0.5px/ms.
const DISMISS_DISTANCE = 120
const DISMISS_VELOCITY = 0.5

// 이 시간(ms) 이상 멈춘 뒤 떼면 종속도 0 — 천천히 끌다 멈추고 놓는 제스처를
// 플릭으로 오판하지 않는다.
const PAUSE_MS = 100

interface DragState {
  pointerId: number
  startY: number
  lastY: number
  lastT: number
  vy: number // 최근 move 구간들의 저역 통과 속도(px/ms) — 종속도 판정용.
  dy: number
}

interface SheetProps {
  ariaLabel: string
  /** slide-down 애니메이션 종료 후 호출 — 부모가 이 시점에 언마운트한다. */
  onClosed: () => void
  /** 헤더 내용 — 닫기 버튼은 Sheet가 공통으로 붙인다. */
  headerContent: ReactNode
  /** 변형 클래스(예: sheet-low — 지오코드 플로우의 낮은 시트). */
  className?: string
  children: ReactNode
}

// bottom sheet 공통 골격 — 핸들·헤더·닫기 버튼·스크롤 바디. DateDetailSheet와
// ClusterSheet가 공유한다(피드백 ②·③). 드래그는 핸들·헤더(.sheet-grab)에서만
// 시작해 바디 그리드 스크롤과 충돌하지 않고, 위 방향은 0으로 고정한다.
export function Sheet({ ariaLabel, onClosed, headerContent, className, children }: SheetProps) {
  const [closing, setClosing] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)
  const dragRef = useRef<DragState | null>(null)

  function onPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    // 닫기 버튼 위에서는 드래그를 시작하지 않는다 — 캡처가 click을 가로채면
    // 기존 닫기 버튼 동작이 깨진다.
    if (closing || (event.target as HTMLElement).closest('button')) return
    const root = rootRef.current
    if (!root) return
    dragRef.current = {
      pointerId: event.pointerId,
      startY: event.clientY,
      lastY: event.clientY,
      lastT: event.timeStamp,
      vy: 0,
      dy: 0,
    }
    try {
      event.currentTarget.setPointerCapture(event.pointerId)
    } catch {
      // 비활성 포인터(합성 이벤트 등) — 캡처 없이도 grab 영역 내 move/up으로 동작.
    }
    root.style.transition = 'none' // 드래그 중 보간 없이 손가락 직추종.
  }

  function onPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current
    const root = rootRef.current
    if (!drag || !root || event.pointerId !== drag.pointerId) return
    const dt = event.timeStamp - drag.lastT
    if (dt > 0) {
      const instant = (event.clientY - drag.lastY) / dt
      // 마지막 한 샘플 대신 최근 추세 — up 직전 샘플의 노이즈에 흔들리지 않게.
      drag.vy = drag.vy === 0 ? instant : instant * 0.6 + drag.vy * 0.4
    }
    drag.lastY = event.clientY
    drag.lastT = event.timeStamp
    drag.dy = Math.max(0, event.clientY - drag.startY) // 위로는 0 고정
    root.style.transform = `translateY(${drag.dy}px)`
  }

  function onPointerEnd(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current
    const root = rootRef.current
    if (!drag || !root || event.pointerId !== drag.pointerId) return
    dragRef.current = null
    const dy = Math.max(0, event.clientY - drag.startY)
    // 종속도: 직전 move 후 PAUSE_MS 내에 뗐으면 진행 중이던 트레일링 속도,
    // 멈췄다 뗐으면 0. up 이벤트는 보통 마지막 move와 같은 좌표로 와서
    // up 구간 자체의 속도는 플릭에서도 0이 된다 — 구간 속도로 판정하면 안 된다.
    const velocity = event.timeStamp - drag.lastT > PAUSE_MS ? 0 : drag.vy
    const dismiss = dy > DISMISS_DISTANCE || velocity > DISMISS_VELOCITY
    if (event.type !== 'pointercancel' && dismiss) {
      // .closing 애니메이션은 현재 translateY(인라인)에서 100%로 이어 내려간다.
      setClosing(true)
    } else {
      root.style.transition = 'transform 0.25s cubic-bezier(0.21, 0.9, 0.32, 1)'
      root.style.transform = '' // spring back — 다음 드래그 시작이 transition을 다시 끈다.
    }
  }

  return (
    <div
      ref={rootRef}
      className={`sheet${className ? ` ${className}` : ''}${closing ? ' closing' : ''}`}
      role="dialog"
      aria-label={ariaLabel}
      onAnimationEnd={(event) => {
        // 자식 애니메이션 버블 무시 — 시트 자신의 slide-down 종료에만 닫는다.
        if (closing && event.target === event.currentTarget) onClosed()
      }}
    >
      <div
        className="sheet-grab"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerEnd}
        onPointerCancel={onPointerEnd}
      >
        <div className="sheet-handle" />
        <header className="sheet-header">
          {headerContent}
          <button type="button" className="ghost" onClick={() => setClosing(true)}>
            닫기
          </button>
        </header>
      </div>
      <div className="sheet-body">{children}</div>
    </div>
  )
}

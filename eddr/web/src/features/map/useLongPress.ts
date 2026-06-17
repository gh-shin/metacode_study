import { useEffect, useRef } from 'react'
import type { RefObject } from 'react'

const HOLD_MS = 650
const MOVE_TOLERANCE_PX = 8

// long-press 감지 — pointerdown 650ms 유지 시 발화, 8px 초과 이동(팬·스크롤)·
// pointerup·취소 시 해제. 데스크톱은 contextmenu(우클릭) 폴백. enabled=false면
// 리스너 자체를 떼서 일반 탐색의 지도 제스처에 개입하지 않는다(S4 수용 기준:
// 스크롤 중 오발화 없음). 좌표는 viewport 기준 clientX/Y로 넘긴다.
export function useLongPress(
  targetRef: RefObject<HTMLElement | null>,
  onLongPress: (clientX: number, clientY: number) => void,
  enabled: boolean,
) {
  // 최신 콜백 참조 — effect 재구독 없이 콜백 교체를 허용한다.
  const handlerRef = useRef(onLongPress)
  handlerRef.current = onLongPress

  useEffect(() => {
    const el = targetRef.current
    if (!enabled || !el) return
    let timer: number | null = null
    let startX = 0
    let startY = 0
    const cancel = () => {
      if (timer !== null) {
        window.clearTimeout(timer)
        timer = null
      }
    }
    const onPointerDown = (event: PointerEvent) => {
      if (!event.isPrimary) {
        cancel() // 두 번째 손가락 = 핀치 시작 — primary의 진행 중 타이머도 취소(품질 리뷰 I3)
        return
      }
      startX = event.clientX
      startY = event.clientY
      cancel()
      timer = window.setTimeout(() => {
        timer = null
        handlerRef.current(startX, startY)
      }, HOLD_MS)
    }
    const onPointerMove = (event: PointerEvent) => {
      if (timer === null || !event.isPrimary) return
      if (Math.hypot(event.clientX - startX, event.clientY - startY) > MOVE_TOLERANCE_PX) {
        cancel()
      }
    }
    const onContextMenu = (event: MouseEvent) => {
      event.preventDefault() // 브라우저 메뉴·MapLibre 기본 동작 차단
      cancel() // 우클릭의 pointerdown 타이머와 이중 발화 방지
      handlerRef.current(event.clientX, event.clientY)
    }
    el.addEventListener('pointerdown', onPointerDown)
    el.addEventListener('pointermove', onPointerMove)
    el.addEventListener('pointerup', cancel)
    el.addEventListener('pointercancel', cancel)
    el.addEventListener('contextmenu', onContextMenu)
    return () => {
      cancel()
      el.removeEventListener('pointerdown', onPointerDown)
      el.removeEventListener('pointermove', onPointerMove)
      el.removeEventListener('pointerup', cancel)
      el.removeEventListener('pointercancel', cancel)
      el.removeEventListener('contextmenu', onContextMenu)
    }
  }, [targetRef, enabled])
}

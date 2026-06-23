import { useCallback, useEffect, useRef, useState } from 'react'

interface Transform {
  scale: number
  x: number
  y: number
}

const MAX_SCALE = 4
const DOUBLE_TAP_MS = 300

// scale를 [1, MAX_SCALE]로 가두는 순수함수 — pinch 핸들러와 self-check가 공유한다.
export function clampScale(scale: number): number {
  return Math.min(MAX_SCALE, Math.max(1, scale))
}

// ponytail: 최소 핀치/팬/더블탭 구현 — 더 정교한 제스처가 필요하면 라이브러리로 교체.
export function usePinchZoom() {
  const ref = useRef<HTMLImageElement | null>(null)
  const [t, setT] = useState<Transform>({ scale: 1, x: 0, y: 0 })
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const pinchStart = useRef<{ dist: number; scale: number } | null>(null)
  const panStart = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null)
  const lastTap = useRef(0)
  const tRef = useRef(t)
  tRef.current = t

  const reset = useCallback(() => setT({ scale: 1, x: 0, y: 0 }), [])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const dist = () => {
      const pts = [...pointers.current.values()]
      return pts.length === 2 ? Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y) : 0
    }
    const onDown = (e: PointerEvent) => {
      el.setPointerCapture(e.pointerId)
      pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
      if (pointers.current.size === 2) {
        pinchStart.current = { dist: dist(), scale: tRef.current.scale }
      } else if (pointers.current.size === 1) {
        const now = e.timeStamp
        if (now - lastTap.current < DOUBLE_TAP_MS) {
          reset()
          lastTap.current = 0
        } else {
          lastTap.current = now
        }
        if (tRef.current.scale > 1) {
          panStart.current = {
            x: e.clientX,
            y: e.clientY,
            tx: tRef.current.x,
            ty: tRef.current.y,
          }
        }
      }
    }
    const onMove = (e: PointerEvent) => {
      if (!pointers.current.has(e.pointerId)) return
      pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
      const start = pinchStart.current
      if (pointers.current.size === 2 && start && start.dist > 0) {
        const ratio = dist() / start.dist
        const scale = clampScale(start.scale * ratio)
        setT((p) => ({ ...p, scale }))
      } else if (pointers.current.size === 1 && panStart.current && tRef.current.scale > 1) {
        const ps = panStart.current
        setT((p) => ({ ...p, x: ps.tx + (e.clientX - ps.x), y: ps.ty + (e.clientY - ps.y) }))
      }
    }
    const onUp = (e: PointerEvent) => {
      pointers.current.delete(e.pointerId)
      if (pointers.current.size < 2) pinchStart.current = null
      if (pointers.current.size === 0) {
        panStart.current = null
        setT((p) => (p.scale <= 1 ? { scale: 1, x: 0, y: 0 } : p))
      }
    }
    el.addEventListener('pointerdown', onDown)
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerup', onUp)
    el.addEventListener('pointercancel', onUp)
    return () => {
      el.removeEventListener('pointerdown', onDown)
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerup', onUp)
      el.removeEventListener('pointercancel', onUp)
    }
  }, [reset])

  const style = {
    transform: `translate(${t.x}px, ${t.y}px) scale(${t.scale})`,
    touchAction: 'none' as const,
  }
  return { ref, style, isZoomed: t.scale > 1, reset }
}

import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { PhotoDetail } from '../../api/client'
import { useStore } from '../../store'
import { NoteEditor } from './NoteEditor'
import { usePinchZoom } from './usePinchZoom'

interface PhotoDetailViewProps {
  photoIds: string[]
  index: number
  onClose: () => void
  onNavigate: (index: number) => void
}

// 시트 위 오버레이 단일 사진 상세(라이트박스 대체) — .sheet 내부에만 깔려 지도는 가리지
// 않는다. 좌표 있으면 열릴 때 지도를 그 위치로 flyTo. 좌/우 버튼·키보드로 넘긴다
// (스와이프는 핀치와 충돌 회피 위해 미구현).
export function PhotoDetailView({ photoIds, index, onClose, onNavigate }: PhotoDetailViewProps) {
  const photoId = photoIds[index]
  const [detail, setDetail] = useState<PhotoDetail | null>(null)
  const flyTo = useStore((s) => s.flyTo)
  const pinch = usePinchZoom()

  useEffect(() => {
    setDetail(null)
    pinch.reset() // 사진 전환 시 확대 상태 이월 방지.
    let cancelled = false
    api
      .detail(photoId)
      .then((next) => {
        if (cancelled) return
        setDetail(next)
        // 좌표 있으면 지도를 그 위치로 — 없으면 카메라 유지.
        if (next.latitude !== null && next.longitude !== null) {
          flyTo([next.longitude, next.latitude], 14, {
            top: 76,
            bottom: Math.round(window.innerHeight * 0.55) + 24,
            left: 40,
            right: 40,
          })
        }
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [photoId, flyTo, pinch.reset])

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      // 메모 입력 중 화살표·ESC가 사진 넘김/닫기로 새지 않게 한다 (M5).
      const target = event.target as HTMLElement | null
      if (target && target.tagName === 'TEXTAREA') return
      if (event.key === 'Escape') onClose()
      if (event.key === 'ArrowLeft' && index > 0) onNavigate(index - 1)
      if (event.key === 'ArrowRight' && index < photoIds.length - 1) onNavigate(index + 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [index, photoIds.length, onClose, onNavigate])

  const location = detail
    ? [detail.city, detail.district, detail.country].filter(Boolean).join(' ')
    : ''
  const camera = detail ? `${detail.camera_make ?? ''} ${detail.camera_model ?? ''}`.trim() : ''
  const size = detail && detail.width && detail.height ? `${detail.width}×${detail.height}` : ''
  const taken = detail?.taken_at ? detail.taken_at.replace('T', ' ').slice(0, 16) : ''

  return (
    <div className="photo-detail" role="dialog" aria-modal="true" aria-label="사진 상세">
      <div className="photo-detail-bar">
        <button type="button" className="photo-detail-back" onClick={onClose} aria-label="뒤로">
          ‹
        </button>
        <span className="photo-detail-count">
          {index + 1} / {photoIds.length}
        </span>
      </div>
      <div className="photo-detail-stage">
        <img
          ref={pinch.ref}
          style={pinch.style}
          src={api.thumbUrl(photoId, 1280)}
          alt={detail?.caption ?? `사진 ${index + 1}`}
        />
        {/* 확대 중엔 네비 버튼을 숨겨 팬 제스처와 충돌하지 않게 한다. */}
        {!pinch.isZoomed && index > 0 && (
          <button
            type="button"
            className="photo-nav photo-nav-prev"
            onClick={() => onNavigate(index - 1)}
            aria-label="이전 사진"
          >
            <span aria-hidden="true">‹</span>
          </button>
        )}
        {!pinch.isZoomed && index < photoIds.length - 1 && (
          <button
            type="button"
            className="photo-nav photo-nav-next"
            onClick={() => onNavigate(index + 1)}
            aria-label="다음 사진"
          >
            <span aria-hidden="true">›</span>
          </button>
        )}
      </div>
      <div className="photo-detail-info">
        {detail && (
          <NoteEditor
            key={detail.photo_id}
            photoId={detail.photo_id}
            initialNote={detail.note}
            date={detail.taken_at ? detail.taken_at.slice(0, 10) : null}
          />
        )}
        <div className="photo-meta">
          {taken && <div>촬영 {taken}</div>}
          {location && <div>{location}</div>}
          {camera && <div>{camera}</div>}
          {size && <div>{size}</div>}
          {detail?.trip_name && <div>{detail.trip_name}</div>}
        </div>
        {detail?.caption && <p className="photo-caption">{detail.caption}</p>}
      </div>
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import type { TouchEvent } from 'react'
import { api } from '../../api/client'
import type { PhotoDetail } from '../../api/client'
import { NoteEditor } from './NoteEditor'

interface LightboxProps {
  photoIds: string[]
  index: number
  onClose: () => void
  onNavigate: (index: number) => void
}

export function Lightbox({ photoIds, index, onClose, onNavigate }: LightboxProps) {
  const photoId = photoIds[index]
  const [detail, setDetail] = useState<PhotoDetail | null>(null)
  const touchStartX = useRef<number | null>(null)

  useEffect(() => {
    setDetail(null)
    let cancelled = false
    api
      .detail(photoId)
      .then((next) => {
        if (!cancelled) setDetail(next)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [photoId])

  const label = detail
    ? [(detail.taken_at ?? '').slice(0, 10), detail.city ?? detail.country ?? '위치 정보 없음']
        .filter(Boolean)
        .join(' · ')
    : ''

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

  function onTouchStart(event: TouchEvent<HTMLElement>) {
    // 두 손가락(핀치줌)은 브라우저 네이티브에 맡기고 한 손가락만 스와이프로 본다.
    touchStartX.current = event.touches.length === 1 ? event.touches[0].clientX : null
  }

  function onTouchEnd(event: TouchEvent<HTMLElement>) {
    if (touchStartX.current === null) return
    const delta = event.changedTouches[0].clientX - touchStartX.current
    touchStartX.current = null
    if (Math.abs(delta) < 48) return
    if (delta > 0 && index > 0) onNavigate(index - 1)
    if (delta < 0 && index < photoIds.length - 1) onNavigate(index + 1)
  }

  return (
    <div className="lightbox" role="dialog" aria-modal="true" aria-label="사진 크게 보기">
      <div className="lightbox-backdrop" onClick={onClose} />
      <figure onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
        <img src={api.thumbUrl(photoId, 1280)} alt={label || `사진 ${index + 1}`} />
        <figcaption>
          <span>{label}</span>
          <span className="lightbox-count">
            {index + 1} / {photoIds.length}
          </span>
        </figcaption>
      </figure>
      {/* 메모(S5) — 상세 패널 하단. 스와이프 핸들러(figure) 밖이라 입력 터치가
          사진 넘김으로 새지 않는다. key=canonical id: 사진 전환 시 리마운트. */}
      {detail && (
        <NoteEditor key={detail.photo_id} photoId={detail.photo_id} initialNote={detail.note} />
      )}
      <div className="lightbox-actions">
        <button type="button" onClick={onClose}>
          닫기
        </button>
        <a href={api.originalUrl(photoId)} download>
          원본 저장
        </a>
      </div>
    </div>
  )
}

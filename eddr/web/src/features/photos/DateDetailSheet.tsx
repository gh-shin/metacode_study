import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import type { DatePhoto } from '../../api/client'
import { useStore } from '../../store'
import type { Bounds } from '../../store'
import { Lightbox } from './Lightbox'
import { Sheet } from './Sheet'

// selectedDate가 있을 때만 마운트된다(App에서 가드) — date는 non-null 전제.
export function DateDetailSheet({ date }: { date: string }) {
  const [photos, setPhotos] = useState<DatePhoto[] | null>(null)
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null)
  const closeDate = useStore((s) => s.closeDate)
  const fitBounds = useStore((s) => s.fitBounds)

  useEffect(() => {
    let cancelled = false
    setPhotos(null)
    setLightboxIndex(null)
    api
      .photosByDate(date)
      .then((res) => {
        if (cancelled) return
        setPhotos(res.photos)
        const bounds = boundsOf(res.photos)
        // GPS 0장이면 카메라 유지(요청 미발행). 패딩은 시트(55%)·상단 바를
        // 제외한 가시 영역 — 마커가 시트에 가리지 않게.
        if (bounds) {
          fitBounds(bounds, {
            top: 76,
            bottom: Math.round(window.innerHeight * 0.55) + 24,
            left: 40,
            right: 40,
          })
        }
      })
      .catch(() => {
        if (!cancelled) setPhotos([])
      })
    return () => {
      cancelled = true
    }
  }, [date, fitBounds])

  const place = useMemo(() => (photos ? topCity(photos) : null), [photos])
  const ids = useMemo(() => (photos ?? []).map((p) => p.photo_id), [photos])

  return (
    <>
      <Sheet
        ariaLabel={`${date} 사진`}
        onClosed={closeDate}
        headerContent={
          <>
            <div>
              <strong>{date}</strong>
              {place && <span className="sheet-place">{place}</span>}
            </div>
            <span className="sheet-count">{photos ? `${photos.length}장` : '…'}</span>
          </>
        }
      >
        {photos && photos.length === 0 && <p className="sheet-empty">사진이 없습니다.</p>}
        <div className="sheet-grid">
          {(photos ?? []).map((photo, index) => (
            <button
              key={photo.photo_id}
              type="button"
              className="cell"
              onClick={() => setLightboxIndex(index)}
              aria-label={`사진 ${index + 1} 크게 보기`}
            >
              <img
                src={api.thumbUrl(photo.photo_id, 320)}
                loading="lazy"
                alt=""
                onError={(event) => {
                  const cell = event.currentTarget.closest('.cell')
                  if (cell instanceof HTMLElement) cell.style.display = 'none'
                }}
              />
            </button>
          ))}
        </div>
      </Sheet>
      {/* 시트 밖 형제로 렌더 — 드래그 중 시트의 inline transform이 fixed 라이트
          박스의 containing block이 되는 것을 피한다. */}
      {lightboxIndex !== null && (
        <Lightbox
          photoIds={ids}
          index={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onNavigate={setLightboxIndex}
        />
      )}
    </>
  )
}

// GPS 있는 사진들의 [[minLng,minLat],[maxLng,maxLat]] — 1장뿐이어도 유효(점 bounds).
function boundsOf(photos: DatePhoto[]): Bounds | null {
  const located = photos.filter(
    (p): p is DatePhoto & { latitude: number; longitude: number } =>
      p.latitude !== null && p.longitude !== null,
  )
  if (located.length === 0) return null
  let minLng = Infinity
  let minLat = Infinity
  let maxLng = -Infinity
  let maxLat = -Infinity
  for (const p of located) {
    minLng = Math.min(minLng, p.longitude)
    maxLng = Math.max(maxLng, p.longitude)
    minLat = Math.min(minLat, p.latitude)
    maxLat = Math.max(maxLat, p.latitude)
  }
  return [
    [minLng, minLat],
    [maxLng, maxLat],
  ]
}

// 최빈 city(없으면 country) — 시트 헤더 장소 라벨.
function topCity(photos: DatePhoto[]): string | null {
  const counts = new Map<string, number>()
  for (const p of photos) {
    const label = p.city ?? p.country
    if (label) counts.set(label, (counts.get(label) ?? 0) + 1)
  }
  let best: string | null = null
  let bestN = 0
  for (const [label, n] of counts) {
    if (n > bestN) {
      best = label
      bestN = n
    }
  }
  return best
}

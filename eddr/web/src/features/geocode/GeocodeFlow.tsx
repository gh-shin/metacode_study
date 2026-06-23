import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api/client'
import type { DatePhoto, GeocodeCandidate, NoLocationGroup } from '../../api/client'
import { useStore } from '../../store'
import type { Bounds } from '../../store'
import { Sheet } from '../photos/Sheet'
import { ConfirmModal } from './ConfirmModal'

const ERROR_TOAST_MS = 4000
// 저장 토스트(주소 + trips 안내 두 줄)를 읽을 시간 — 지나면 드로어 복귀.
const SAVED_RETURN_MS = 2500

// 그룹 1개의 장소 검색 + 사진 그리드 패널(S4) — expandable 시트로 그리드 높이를
// 확보한다. 검색 → 후보 ≤5 리스트 + 지도 핀(MapView 전용 source), 후보 탭 =
// flyTo(zoom 14) + 핀 강조. 지도 long-press(MapView 훅)는 후보 0건이어도 항상
// 열려 있는 경로. 그리드는 그날 전체 사진(위치 有/無) — GPS 없는 사진만 다중
// 선택해 target을 적용하고, 위치 있는 사진은 탭하면 기준점(좌표 보존)이 된다.
// "여기로 지정" → ConfirmModal → PUT(선택 사진만) → 토스트 → 드로어 복귀.
export function GeocodeFlow({ group }: { group: NoLocationGroup }) {
  const [text, setText] = useState('')
  const [searching, setSearching] = useState(false)
  const [searched, setSearched] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<{ message: string; hint?: string } | null>(null)
  const [photos, setPhotos] = useState<DatePhoto[] | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const timersRef = useRef<number[]>([])
  const candidates = useStore((s) => s.geocodeCandidates)
  const target = useStore((s) => s.geocodeTarget)
  const setGeocodeCandidates = useStore((s) => s.setGeocodeCandidates)
  const setGeocodeTarget = useStore((s) => s.setGeocodeTarget)
  const selectGeocodeCandidate = useStore((s) => s.selectGeocodeCandidate)
  const backToGeocodeList = useStore((s) => s.backToGeocodeList)
  const bumpNoLocation = useStore((s) => s.bumpNoLocation)
  const refreshMapPhotos = useStore((s) => s.refreshMapPhotos)
  const fitBounds = useStore((s) => s.fitBounds)
  const flyTo = useStore((s) => s.flyTo)

  // 마운트 시 그날 전체 사진 로드 — GPS 없는 사진을 기본 전체 선택으로 초기화.
  useEffect(() => {
    let cancelled = false
    api
      .photosByDate(group.date)
      .then((res) => {
        if (cancelled) return
        const missing = res.photos.filter((p) => p.latitude === null || p.longitude === null)
        const focus =
          group.focus_photo_id && missing.some((p) => p.photo_id === group.focus_photo_id)
            ? [group.focus_photo_id]
            : missing.map((p) => p.photo_id)
        setPhotos(res.photos)
        setSelected(new Set(focus))
      })
      .catch(() => {
        if (!cancelled) setPhotos([])
      })
    return () => {
      cancelled = true
    }
  }, [group.date, group.focus_photo_id])

  const missingIds = useMemo(
    () =>
      (photos ?? [])
        .filter((p) => p.latitude === null || p.longitude === null)
        .map((p) => p.photo_id),
    [photos],
  )
  const allSelected = missingIds.length > 0 && missingIds.every((id) => selected.has(id))

  function toggleSelected(photoId: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(photoId)) next.delete(photoId)
      else next.add(photoId)
      return next
    })
  }

  function toggleSelectAll() {
    setSelected(allSelected ? new Set() : new Set(missingIds))
  }

  function pickReference(photo: DatePhoto) {
    if (photo.latitude === null || photo.longitude === null) return
    setGeocodeTarget({ latitude: photo.latitude, longitude: photo.longitude, candidate: null })
    flyTo([photo.longitude, photo.latitude], 14)
  }

  useEffect(
    () => () => {
      timersRef.current.forEach((timer) => window.clearTimeout(timer))
    },
    [],
  )

  function later(fn: () => void, ms: number) {
    timersRef.current.push(window.setTimeout(fn, ms))
  }

  function showError(message: string) {
    setToast({ message })
    later(() => setToast(null), ERROR_TOAST_MS)
  }

  async function submitSearch(event: FormEvent) {
    event.preventDefault()
    const query = text.trim()
    if (!query || searching) return
    setSearching(true)
    try {
      const res = await api.geocodeSearch(query)
      setGeocodeCandidates(res.candidates)
      setSearched(true)
      // 유저 스토리: "검색하자 지도가 후보지로 날아간다" — 전 후보가 보이게.
      const bounds = candidateBounds(res.candidates)
      if (bounds) {
        fitBounds(bounds, {
          top: 76,
          bottom: Math.round(window.innerHeight * 0.42) + 24,
          left: 40,
          right: 40,
        })
      }
    } catch (err) {
      showError(err instanceof Error ? err.message : '장소 검색에 실패했습니다.')
    } finally {
      setSearching(false)
    }
  }

  async function save() {
    if (!target || selected.size === 0 || saving) return
    setSaving(true)
    try {
      const ids = [...selected] // 전부 GPS 없는 사진(선택 규칙상 보장)
      const res = await api.updateLocation(ids, target.latitude, target.longitude)
      setConfirming(false)
      bumpNoLocation() // 배지·드로어 재조회
      refreshMapPhotos() // /api/map/photos 강제 재요청 — 새 마커
      const place = [res.country, res.city, res.district].filter(Boolean).join(' ')
      setToast({
        message: place
          ? `${res.updated}장 저장 — ${place}`
          : `${res.updated}장 저장 — 주소 자동 조회 실패(좌표는 저장됨)`,
        hint: 'trip 반영은 eddr trips recompute로 실행하세요.',
      })
      later(backToGeocodeList, SAVED_RETURN_MS)
    } catch (err) {
      setConfirming(false)
      showError(err instanceof Error ? err.message : '저장에 실패했습니다.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      {toast && (
        <div className={`toast${toast.hint ? ' toast-info' : ''}`} role="status">
          {toast.message}
          {toast.hint && <small>{toast.hint}</small>}
        </div>
      )}
      <Sheet
        expandable
        ariaLabel={`${group.date} 위치 지정`}
        onClosed={backToGeocodeList}
        onBack={backToGeocodeList}
        headerContent={
          <div>
            <strong>{group.date}</strong>
            <span className="sheet-place">{group.count}장 위치 지정</span>
          </div>
        }
      >
        <form className="geocode-search" onSubmit={submitSearch}>
          <input
            type="search"
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="장소 검색 — 예: 서산 개심사"
            aria-label="장소 검색"
            enterKeyHint="search"
            autoComplete="off"
          />
          <button type="submit" disabled={searching}>
            {searching ? '…' : '검색'}
          </button>
        </form>
        <p className="geocode-hint">
          {searched && candidates.length === 0
            ? '후보가 없어요 — 지도를 길게(0.7초) 눌러 직접 지정해 주세요.'
            : '검색하거나, 지도를 길게 눌러 직접 지정할 수 있어요.'}
        </p>
        {candidates.length > 0 && (
          <ul className="geocode-candidates">
            {candidates.map((candidate, index) => (
              <li key={`${candidate.latitude},${candidate.longitude},${index}`}>
                <button
                  type="button"
                  className={`geocode-candidate${
                    target?.candidate === candidate ? ' selected' : ''
                  }`}
                  onClick={() => selectGeocodeCandidate(candidate)}
                >
                  <strong>{shortName(candidate)}</strong>
                  <span>{candidate.name}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {missingIds.length > 0 && (
          <div className="geo-select-bar">
            <button type="button" className="ghost" onClick={toggleSelectAll}>
              {allSelected ? '전체 해제' : '전체 선택'}
            </button>
            <span>선택 {selected.size}장</span>
          </div>
        )}
        <div className="geo-grid">
          {(photos ?? []).map((photo) => {
            const isMissing = photo.latitude === null || photo.longitude === null
            const isRef =
              !!target && target.latitude === photo.latitude && target.longitude === photo.longitude
            return (
              <button
                key={photo.photo_id}
                type="button"
                className={`geo-cell${isMissing ? '' : ' geo-cell-located'}${
                  isMissing && selected.has(photo.photo_id) ? ' selected' : ''
                }${isRef ? ' is-ref' : ''}`}
                aria-pressed={isMissing ? selected.has(photo.photo_id) : undefined}
                onClick={() =>
                  isMissing ? toggleSelected(photo.photo_id) : pickReference(photo)
                }
              >
                <img
                  src={api.thumbUrl(photo.photo_id, 320)}
                  loading="lazy"
                  alt=""
                  onError={(event) => {
                    const cell = event.currentTarget.closest('.geo-cell')
                    if (cell instanceof HTMLElement) cell.style.display = 'none'
                  }}
                />
                {!isMissing && <span className="geo-cell-badge">📍</span>}
              </button>
            )
          })}
        </div>
        {photos && missingIds.length === 0 && (
          <p className="sheet-empty">이미 모두 위치가 지정된 그룹입니다.</p>
        )}
        <button
          type="button"
          className="geocode-apply"
          disabled={!target || selected.size === 0}
          onClick={() => setConfirming(true)}
        >
          {target ? `여기로 지정 (${selected.size}장)` : '후보·기준 사진·지도를 길게 눌러 위치를 정하세요'}
        </button>
      </Sheet>
      {/* 시트 밖 형제로 렌더 — 드래그 중 시트 inline transform 영향 회피(기존 패턴). */}
      {confirming && target && (
        <ConfirmModal
          date={group.date}
          count={selected.size}
          sampleIds={[...selected].slice(0, 4)}
          target={target}
          saving={saving}
          onConfirm={save}
          onCancel={() => setConfirming(false)}
        />
      )}
    </>
  )
}

// 후보 대표 이름 — display_name 첫 토큰(예: "개심사"). 전체 주소는 아랫줄에.
function shortName(candidate: GeocodeCandidate): string {
  return candidate.name.split(',')[0]?.trim() || candidate.name
}

// 후보 전체를 덮는 bounds — 1건이어도 유효(점 bounds, applyCamera maxZoom 15).
function candidateBounds(candidates: GeocodeCandidate[]): Bounds | null {
  if (candidates.length === 0) return null
  let minLng = Infinity
  let minLat = Infinity
  let maxLng = -Infinity
  let maxLat = -Infinity
  for (const candidate of candidates) {
    minLng = Math.min(minLng, candidate.longitude)
    maxLng = Math.max(maxLng, candidate.longitude)
    minLat = Math.min(minLat, candidate.latitude)
    maxLat = Math.max(maxLat, candidate.latitude)
  }
  return [
    [minLng, minLat],
    [maxLng, maxLat],
  ]
}

import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api/client'
import type { GeocodeCandidate, NoLocationGroup } from '../../api/client'
import { useStore } from '../../store'
import type { Bounds } from '../../store'
import { Sheet } from '../photos/Sheet'
import { ConfirmModal } from './ConfirmModal'

const ERROR_TOAST_MS = 4000
// 저장 토스트(주소 + trips 안내 두 줄)를 읽을 시간 — 지나면 드로어 복귀.
const SAVED_RETURN_MS = 2500

// 그룹 1개의 장소 검색 패널(S4) — 낮은 시트(sheet-low)로 지도를 넓게 남긴다.
// 검색 → 후보 ≤5 리스트 + 지도 핀(MapView 전용 source), 후보 탭 = flyTo(zoom 14)
// + 핀 강조. 지도 long-press(MapView 훅)는 후보 0건이어도 항상 열려 있는 경로.
// "여기로 지정" → ConfirmModal → PUT → 토스트 → 드로어 복귀(시트 닫기도 복귀).
export function GeocodeFlow({ group }: { group: NoLocationGroup }) {
  const [text, setText] = useState('')
  const [searching, setSearching] = useState(false)
  const [searched, setSearched] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState<{ message: string; hint?: string } | null>(null)
  const timersRef = useRef<number[]>([])
  const candidates = useStore((s) => s.geocodeCandidates)
  const target = useStore((s) => s.geocodeTarget)
  const setGeocodeCandidates = useStore((s) => s.setGeocodeCandidates)
  const selectGeocodeCandidate = useStore((s) => s.selectGeocodeCandidate)
  const backToGeocodeList = useStore((s) => s.backToGeocodeList)
  const bumpNoLocation = useStore((s) => s.bumpNoLocation)
  const refreshMapPhotos = useStore((s) => s.refreshMapPhotos)
  const fitBounds = useStore((s) => s.fitBounds)

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
    if (!target || saving) return
    setSaving(true)
    try {
      // 그룹 전체 photo_ids — no-location 응답엔 대표 4장뿐이라(payload 절약)
      // by-date에서 그날 GPS 없는 사진을 다시 모은다(동일 노출 모집단).
      const byDate = await api.photosByDate(group.date)
      const ids = byDate.photos.filter((p) => p.latitude === null).map((p) => p.photo_id)
      if (ids.length === 0) throw new Error('지정할 사진이 없어요 — 이미 처리된 그룹입니다.')
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
        className="sheet-low"
        ariaLabel={`${group.date} 위치 지정`}
        onClosed={backToGeocodeList}
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
        <button
          type="button"
          className="geocode-apply"
          disabled={!target}
          onClick={() => setConfirming(true)}
        >
          {target
            ? target.candidate
              ? '여기로 지정'
              : '여기로 지정 (직접 선택한 지점)'
            : '후보를 탭하거나 지도를 길게 누르세요'}
        </button>
      </Sheet>
      {/* 시트 밖 형제로 렌더 — 드래그 중 시트 inline transform 영향 회피(기존 패턴). */}
      {confirming && target && (
        <ConfirmModal
          group={group}
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

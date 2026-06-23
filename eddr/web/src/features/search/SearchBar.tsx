import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api } from '../../api/client'
import type { SearchResponse } from '../../api/client'
import { useStore } from '../../store'
import type { Bounds } from '../../store'

// 오류 토스트 표시 시간(ms) — 503 detail(한국어)을 그대로 보여 준다.
const TOAST_MS = 4000

// 하단 고정 플로팅 검색바 — 시트(z-index 20)보다 위라 어디서든 재검색 가능.
// 제출 → POST /api/search → 결과를 store에 반영하고, 최상위 lane의 GPS 사진으로
// fitBounds를 발행한다(시트 패딩 — DateDetailSheet와 동일 패턴).
export function SearchBar() {
  const [text, setText] = useState('')
  const [toast, setToast] = useState<string | null>(null)
  const toastTimer = useRef<number | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const searching = useStore((s) => s.searching)
  const beginSearch = useStore((s) => s.beginSearch)
  const finishSearch = useStore((s) => s.finishSearch)
  const failSearch = useStore((s) => s.failSearch)
  const fitBounds = useStore((s) => s.fitBounds)
  const pendingQuery = useStore((s) => s.pendingQuery)
  const clearPendingQuery = useStore((s) => s.clearPendingQuery)

  useEffect(
    () => () => {
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current)
    },
    [],
  )

  // 예시 칩 트리거 — pendingQuery 값 있으면 입력창 채우고 즉시 검색.
  useEffect(() => {
    if (!pendingQuery) return
    setText(pendingQuery)
    clearPendingQuery()
    void runQuery(pendingQuery)
    // pendingQuery 변경 시점의 렌더에서 최신 runQuery(및 zustand 최신값)를
    // 클로저로 캡처하므로 stale closure 없음 — deps 제외 안전.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingQuery])

  function showToast(message: string) {
    setToast(message)
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), TOAST_MS)
  }

  // 검색 본문 — submit과 pendingQuery effect 양쪽이 호출한다.
  async function runQuery(query: string) {
    inputRef.current?.blur()
    if (!query || searching) return
    beginSearch()
    try {
      const result = await api.search(query)
      finishSearch(query, result)
      const bounds = topLaneBounds(result)
      // 최상위 lane에 GPS 사진이 없으면 카메라 유지(요청 미발행) — by-date 패턴 동일.
      if (bounds) {
        fitBounds(bounds, {
          top: 76,
          bottom: Math.round(window.innerHeight * 0.55) + 24,
          left: 40,
          right: 40,
        })
      }
    } catch (err) {
      failSearch()
      showToast(err instanceof Error ? err.message : '검색에 실패했습니다.')
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    await runQuery(text.trim())
  }

  return (
    <>
      {toast && (
        <div className="toast" role="alert">
          {toast}
        </div>
      )}
      <form className="searchbar" onSubmit={submit}>
        <input
          ref={inputRef}
          type="search"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="사진 검색 — 예: 몽골 은하수"
          aria-label="사진 검색"
          enterKeyHint="search"
          autoComplete="off"
        />
        {searching ? (
          <span className="spinner" role="status" aria-label="검색 중" />
        ) : (
          <button type="submit" aria-label="검색">
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path
                d="M10.5 3a7.5 7.5 0 1 0 4.6 13.4l4.7 4.7 1.4-1.4-4.7-4.7A7.5 7.5 0 0 0 10.5 3zm0 2a5.5 5.5 0 1 1 0 11 5.5 5.5 0 0 1 0-11z"
                fill="currentColor"
              />
            </svg>
          </button>
        )}
      </form>
    </>
  )
}

// 최상위 lane GPS 사진들의 bounds — 1장뿐이어도 유효(점 bounds). 없으면 null.
function topLaneBounds(result: SearchResponse): Bounds | null {
  const top = result.groups[0]
  if (!top) return null
  let minLng = Infinity
  let minLat = Infinity
  let maxLng = -Infinity
  let maxLat = -Infinity
  let found = false
  for (const photo of top.photos) {
    if (photo.latitude === null || photo.longitude === null) continue
    found = true
    minLng = Math.min(minLng, photo.longitude)
    maxLng = Math.max(maxLng, photo.longitude)
    minLat = Math.min(minLat, photo.latitude)
    maxLat = Math.max(maxLat, photo.latitude)
  }
  if (!found) return null
  return [
    [minLng, minLat],
    [maxLng, maxLat],
  ]
}

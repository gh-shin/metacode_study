import { useEffect } from 'react'
import { api } from '../../api/client'
import { useStore } from '../../store'

// 상단 우측 빨간 느낌표 배지 — 잔여 그룹 수(S4 진입점). 마운트 시 1회 +
// 저장 성공(noLocationSeq) 후 재조회한다. 0이면 숨김.
export function NoLocationBadge() {
  const count = useStore((s) => s.noLocationCount)
  const seq = useStore((s) => s.noLocationSeq)
  const setNoLocationCount = useStore((s) => s.setNoLocationCount)
  const openGeocode = useStore((s) => s.openGeocode)

  useEffect(() => {
    let cancelled = false
    api
      .noLocation()
      .then((res) => {
        if (!cancelled) setNoLocationCount(res.groups.length)
      })
      .catch(() => undefined) // 조회 실패 — 배지만 안 뜨고 다른 기능은 무관.
    return () => {
      cancelled = true
    }
  }, [seq, setNoLocationCount])

  if (!count) return null
  return (
    <button
      type="button"
      className="noloc-badge"
      onClick={openGeocode}
      aria-label={`위치 미상 ${count}개 그룹 — 위치 지정하기`}
    >
      <span className="noloc-bang" aria-hidden="true">
        !
      </span>
      {count.toLocaleString()}
    </button>
  )
}

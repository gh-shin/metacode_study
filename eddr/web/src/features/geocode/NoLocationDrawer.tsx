import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import type { NoLocationResponse } from '../../api/client'
import { useStore } from '../../store'
import { Sheet } from '../photos/Sheet'

// 위치 미상 일별 그룹 드로어(S4) — Sheet 셸 재사용. 카드 = 날짜·N장·대표
// 썸네일 4·trip 힌트 칩·진행 카운트(i/전체). 카드 탭 → GeocodeFlow(그룹 선택).
// 저장 성공(noLocationSeq) 후 재조회로 해소된 그룹이 빠진다.
export function NoLocationDrawer() {
  const [data, setData] = useState<NoLocationResponse | null>(null)
  const [error, setError] = useState(false)
  const seq = useStore((s) => s.noLocationSeq)
  const closeGeocode = useStore((s) => s.closeGeocode)
  const selectGeocodeGroup = useStore((s) => s.selectGeocodeGroup)

  useEffect(() => {
    let cancelled = false
    setError(false)
    api
      .noLocation()
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch(() => {
        // 오류를 빈 데이터로 치환하면 "없습니다 🎉" 허위 완료가 뜬다(품질 리뷰 I4).
        if (!cancelled) setError(true)
      })
    return () => {
      cancelled = true
    }
  }, [seq])

  return (
    <Sheet
      ariaLabel="위치 미상 사진"
      onClosed={closeGeocode}
      headerContent={
        <div>
          <strong>위치 미상</strong>
          {data && (
            <span className="sheet-place">
              {data.groups.length.toLocaleString()}그룹 · {data.total_photos.toLocaleString()}장
            </span>
          )}
        </div>
      }
    >
      {error && <p className="sheet-empty">목록을 불러오지 못했어요 — 닫았다가 다시 열어 주세요.</p>}
      {!error && !data && <p className="sheet-empty">불러오는 중…</p>}
      {!error && data && data.groups.length === 0 && (
        <p className="sheet-empty">위치 미상 사진이 없습니다 🎉</p>
      )}
      {data?.groups.map((group, index) => (
        <button
          key={group.date}
          type="button"
          className="noloc-card"
          onClick={() => selectGeocodeGroup(group)}
          aria-label={`${group.date} ${group.count}장 위치 지정하기`}
        >
          <div className="noloc-card-thumbs">
            {group.sample_photo_ids.map((id) => (
              <img key={id} src={api.thumbUrl(id, 320)} loading="lazy" alt="" />
            ))}
          </div>
          <div className="noloc-card-meta">
            <strong>{group.date}</strong>
            <span className="noloc-card-count">{group.count}장</span>
            {group.trip_name && <span className="chip">{group.trip_name}</span>}
            {/* 진행 표시 — 단순 카운트("전체 중 N번째"). */}
            <span className="noloc-card-index">
              {index + 1}/{data.groups.length}
            </span>
          </div>
        </button>
      ))}
    </Sheet>
  )
}

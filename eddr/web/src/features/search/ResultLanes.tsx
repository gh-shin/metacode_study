import { useState } from 'react'
import type { MouseEvent } from 'react'
import { api } from '../../api/client'
import type { SearchGroup, SearchPhoto } from '../../api/client'
import { useStore } from '../../store'

// lane당 접힘 노출 수 — 5번째 뒤 '더보기' 셀(scenario v2 S2, 뷰포트 ~3장 marquee).
const TOP_N = 5
const UNDATED = '날짜 미상'

interface ResultLanesProps {
  // /api/search groups 그대로 — 서버가 KST 그룹핑·관련도 정렬을 끝낸 상태(prd §6-b).
  groups: SearchGroup[]
  onOpen: (photoIds: string[], index: number) => void
}

// 검색 결과 날짜 lane — 구 DateLanes(채팅용)를 개조: fetch 없이 groups를 받고,
// '더보기'·헤더 탭은 펼침이 아니라 날짜 상세(S3, returnTo='search')로 진입한다.
export function ResultLanes({ groups, onOpen }: ResultLanesProps) {
  const openDate = useStore((s) => s.openDate)
  const openGeocode = useStore((s) => s.openGeocode)
  const selectGeocodeGroup = useStore((s) => s.selectGeocodeGroup)
  // 날짜 미상 lane 전용 — by-date 진입이 불가능해 제자리 펼침으로 대체한다.
  const [undatedOpen, setUndatedOpen] = useState(false)

  function openLocationFlow(
    event: MouseEvent<HTMLButtonElement>,
    photo: SearchPhoto,
    date: string | null,
  ) {
    event.stopPropagation()
    openGeocode()
    if (date === null) return
    selectGeocodeGroup({
      date,
      count: 1,
      sample_photo_ids: [photo.photo_id],
      trip_name: null,
      focus_photo_id: photo.photo_id,
    })
  }

  return (
    <div className="lanes">
      {groups.map((group) => {
        const date = group.date
        const label = date ?? UNDATED
        const laneIds = group.photos.map((photo) => photo.photo_id)
        const isOpen = date === null && undatedOpen
        const visible = isOpen ? group.photos : group.photos.slice(0, TOP_N)
        const hidden = group.photos.length - visible.length
        const headerBody = (
          <>
            <strong>{label}</strong>
            {group.place && <span className="lane-place">{group.place}</span>}
            <span className="lane-count">
              {group.photos.length}장{date !== null && ' ›'}
            </span>
          </>
        )
        return (
          <section key={label} className="lane-section" aria-label={label}>
            {date !== null ? (
              <button
                type="button"
                className="lane-header"
                onClick={() => openDate(date)}
                aria-label={`${date} 전체 보기`}
              >
                {headerBody}
              </button>
            ) : (
              <header className="lane-header">{headerBody}</header>
            )}
            <div className="lane">
              {visible.map((photo, index) => {
                const missingLocation = photo.latitude === null || photo.longitude === null
                return (
                  <div key={photo.photo_id} className="cell lane-cell">
                    <button
                      type="button"
                      className="lane-photo-button"
                      onClick={() => onOpen(laneIds, index)}
                      aria-label={`${label} 사진 ${index + 1} 크게 보기`}
                    >
                      <img
                        src={api.thumbUrl(photo.photo_id, 320)}
                        loading="lazy"
                        alt=""
                        onError={(event) => {
                          // 원본 유실 등 404는 셀 자체를 숨긴다.
                          const cell = event.currentTarget.closest('.cell')
                          if (cell instanceof HTMLElement) cell.style.display = 'none'
                        }}
                      />
                    </button>
                    {missingLocation && (
                      <button
                        type="button"
                        className="lane-locate-button"
                        title="위치 지정"
                        aria-label={
                          date === null
                            ? '위치 미상 목록에서 위치 지정하기'
                            : `${label} 사진 ${index + 1} 위치 지정하기`
                        }
                        onClick={(event) => openLocationFlow(event, photo, date)}
                      >
                        <span aria-hidden="true">!</span>
                      </button>
                    )}
                  </div>
                )
              })}
              {hidden > 0 && (
                <button
                  type="button"
                  className="cell lane-more"
                  onClick={() => (date !== null ? openDate(date) : setUndatedOpen(true))}
                  aria-label={date !== null ? `${date} 전체 보기` : '나머지 펼치기'}
                >
                  +{hidden}
                  <small>더보기</small>
                </button>
              )}
            </div>
          </section>
        )
      })}
    </div>
  )
}

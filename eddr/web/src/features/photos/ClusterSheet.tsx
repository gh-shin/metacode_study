import { useMemo, useState } from 'react'
import { api } from '../../api/client'
import { useStore } from '../../store'
import type { ClusterLeaf, ClusterSelection } from '../../store'
import { Lightbox } from './Lightbox'
import { Sheet } from './Sheet'

interface Section {
  date: string
  ids: string[]
}

// 클러스터 탭 즉시 표출 시트(피드백 ③) — leaves를 날짜 내림차순 섹션으로 묶고,
// 날짜 헤더 탭 = 그 날짜의 DateDetailSheet로 전환(by-date 전체, 뒤로가기 없음).
// 카메라는 움직이지 않는다 — 줌은 네이티브 더블탭/핀치에 위임.
export function ClusterSheet({ cluster }: { cluster: ClusterSelection }) {
  const closeCluster = useStore((s) => s.closeCluster)
  const openDate = useStore((s) => s.openDate)
  // 라이트박스 컨텍스트는 탭한 섹션의 사진 목록 — 시트 전체가 아니다.
  const [lightbox, setLightbox] = useState<{ ids: string[]; index: number } | null>(null)

  const sections = useMemo(() => groupByDateDesc(cluster.leaves), [cluster.leaves])
  const truncated = cluster.total > cluster.leaves.length

  return (
    <>
      <Sheet
        ariaLabel="이 영역 사진"
        onClosed={closeCluster}
        headerContent={
          <div>
            <strong>
              이 영역 {cluster.total.toLocaleString()}장 · {sections.length}일
            </strong>
            {truncated && <span className="sheet-place">(상위 1,000장)</span>}
          </div>
        }
      >
        {sections.map((section) => (
          <section className="cluster-section" key={section.date}>
            <button
              type="button"
              className="cluster-section-header"
              onClick={() => openDate(section.date)}
              aria-label={`${section.date} 전체 보기`}
            >
              <strong>{section.date}</strong>
              <span>{section.ids.length}장 ›</span>
            </button>
            <div className="sheet-grid">
              {section.ids.map((id, index) => (
                <button
                  key={id}
                  type="button"
                  className="cell"
                  onClick={() => setLightbox({ ids: section.ids, index })}
                  aria-label={`사진 ${index + 1} 크게 보기`}
                >
                  <img
                    src={api.thumbUrl(id, 320)}
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
          </section>
        ))}
      </Sheet>
      {/* 시트 밖 형제로 렌더 — 드래그 중 시트의 inline transform 영향 회피. */}
      {lightbox && (
        <Lightbox
          photoIds={lightbox.ids}
          index={lightbox.index}
          onClose={() => setLightbox(null)}
          onNavigate={(index) => setLightbox({ ids: lightbox.ids, index })}
        />
      )}
    </>
  )
}

// 날짜 내림차순(최신 먼저) 섹션 — leaves 순서는 클러스터 내부 순서라 보장이 없다.
function groupByDateDesc(leaves: ClusterLeaf[]): Section[] {
  const byDate = new Map<string, string[]>()
  for (const leaf of leaves) {
    const ids = byDate.get(leaf.date)
    if (ids) ids.push(leaf.id)
    else byDate.set(leaf.date, [leaf.id])
  }
  return [...byDate.entries()]
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([date, ids]) => ({ date, ids }))
}

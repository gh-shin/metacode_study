import { useStore } from '../../store'

// 검색 전 홈 안내 — 예시 질의 칩 탭 시 즉시 검색.
// mode=browse & searchResult=null 일 때만 App이 마운트한다.
const EXAMPLE_QUERIES = [
  '몽골 은하수',
  '제주 현무암 해변',
  '개심사 벚꽃',
  '작년 여름 바다',
] as const

export function EmptyState() {
  const setPendingQuery = useStore((s) => s.setPendingQuery)

  return (
    <div className="empty-state" aria-label="검색 안내">
      <p className="empty-state-hint">사진에게 물어보세요</p>
      <div className="chips">
        {EXAMPLE_QUERIES.map((q) => (
          <button
            key={q}
            type="button"
            className="chip"
            onClick={() => setPendingQuery(q)}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}

import type { StatusResponse } from '../../api/client'
import { Sheet } from '../photos/Sheet'

// indexing_status 키 → 한국어 라벨 매핑(알 수 없는 키는 그대로 표시).
// 키 출처: src/eddr/db/repository.py L15–L19 (INDEXING_STATUS 상수) 및 indexing_stage_counts() 쿼리.
const STAGE_LABELS: Record<string, string> = {
  trip_assigned: '캡션·trip 색인 완료',
  caption_done: '캡션 완료(trip 미배정)',
  meta_done: '메타 완료(캡션 대기)',
  missing_image: '이미지 없음',
  skipped_video: '동영상(제외)',
}

interface StatusSheetProps {
  status: StatusResponse
  onClose: () => void
}

export function StatusSheet({ status, onClose }: StatusSheetProps) {
  return (
    <Sheet
      className="sheet-low"
      ariaLabel="색인 상태"
      onClosed={onClose}
      headerContent={<strong>색인 상태</strong>}
    >
      <div className="status-sheet-body">
        {/* 핵심 수치 */}
        <p className="status-summary">
          <span className="status-ready">{status.ready.toLocaleString()}</span>
          {' 검색 가능 / 전체 모집단 '}
          <span className="status-total">{status.total.toLocaleString()}</span>
        </p>
        <p className="status-desc">
          검색 가능 = 캡션·trip 색인 완료분.
          동영상·중복 제외 모집단 {status.total.toLocaleString()}장 중{' '}
          {status.ready.toLocaleString()}장이 검색 대상입니다.
        </p>

        {/* path_health 경고 */}
        {!status.path_health.healthy && (
          <p className="status-warn">
            ⚠️ 경로 확인 필요 — 일부 사진 파일에 접근할 수 없습니다 (점검:{' '}
            {status.path_health.sampled}장 중 {status.path_health.ok}장 정상).
          </p>
        )}

        {/* 단계별 분포 */}
        <table className="status-stages">
          <thead>
            <tr>
              <th>단계</th>
              <th>사진 수</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(status.stages).map(([key, count]) => (
              <tr key={key}>
                <td>{STAGE_LABELS[key] ?? key}</td>
                <td>{count.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Sheet>
  )
}

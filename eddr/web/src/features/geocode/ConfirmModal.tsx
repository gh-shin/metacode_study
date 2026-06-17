import { api } from '../../api/client'
import type { NoLocationGroup } from '../../api/client'
import type { GeocodeTarget } from '../../store'

interface ConfirmModalProps {
  group: NoLocationGroup
  target: GeocodeTarget
  saving: boolean
  onConfirm: () => void
  onCancel: () => void
}

// 위치 지정 확인 모달(중앙 카드) — "이 날짜 N장 전체에 적용" + 대표 썸네일 4 +
// 후보 선택이면 주소 미리보기, long-press면 "저장 후 주소 자동 조회" 안내.
export function ConfirmModal({ group, target, saving, onConfirm, onCancel }: ConfirmModalProps) {
  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="위치 지정 확인">
      <div className="modal-card">
        <strong className="modal-title">
          {group.date} · {group.count}장 전체에 적용
        </strong>
        <div className="modal-thumbs">
          {group.sample_photo_ids.map((id) => (
            <img key={id} src={api.thumbUrl(id, 320)} alt="" />
          ))}
        </div>
        {target.candidate ? (
          <p className="modal-address">{target.candidate.name}</p>
        ) : (
          <p className="modal-address modal-muted">
            저장 후 주소를 자동 조회합니다 ({target.latitude.toFixed(5)},{' '}
            {target.longitude.toFixed(5)})
          </p>
        )}
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onCancel} disabled={saving}>
            취소
          </button>
          <button type="button" className="modal-primary" onClick={onConfirm} disabled={saving}>
            {saving ? '저장 중…' : '이 위치로 저장'}
          </button>
        </div>
      </div>
    </div>
  )
}

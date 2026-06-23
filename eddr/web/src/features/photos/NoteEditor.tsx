import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'

const TOAST_MS = 3000

interface NoteEditorProps {
  photoId: string // canonical id — detail.photo_id (duplicate 정체성 일치, ADR-0002)
  initialNote: string | null
  date: string | null // 촬영일(YYYY-MM-DD) — 있으면 저장 후 같은 날 일괄 확인 패널 노출.
}

// 상세 뷰 하단의 메모 영역(S5) — 사진별 1메모.
// 메모 있음: 본문 노출(탭=편집) ↔ 없음/편집: textarea + 저장(+삭제).
// 저장은 동기 임베딩 — embedded:false(ollama 다운)면 "다시 저장" 안내를 띄운다.
export function NoteEditor({ photoId, initialNote, date }: NoteEditorProps) {
  const [note, setNote] = useState(initialNote)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(initialNote ?? '')
  const [busy, setBusy] = useState(false)
  const [askDay, setAskDay] = useState(false)
  const [toast, setToast] = useState<{ message: string; error?: boolean } | null>(null)
  const timerRef = useRef<number | null>(null)

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    },
    [],
  )

  function showToast(message: string, error = false) {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    setToast({ message, error })
    timerRef.current = window.setTimeout(() => setToast(null), TOAST_MS)
  }

  async function save() {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    setBusy(true)
    try {
      const res = await api.putNote(photoId, trimmed)
      setNote(res.text)
      setText(res.text)
      setEditing(false)
      showToast(res.embedded ? '메모 저장됨' : '저장됨 — 검색 반영은 ollama 실행 후 다시 저장')
      if (date) setAskDay(true) // 같은 날 일괄 적용 권유.
    } catch (err) {
      showToast(err instanceof Error ? err.message : '메모 저장에 실패했습니다.', true)
    } finally {
      setBusy(false)
    }
  }

  // 같은 날 노트 없는 사진들에 방금 저장한 메모를 일괄 적용(서버가 빈 사진만 채움).
  async function applyToDay() {
    if (!date || busy) return
    setBusy(true)
    try {
      const res = await api.putNoteByDate(date, text.trim())
      showToast(
        res.embedded < res.applied
          ? `${res.applied}장에 적용 — 검색 반영은 ollama 실행 후`
          : `${res.applied}장에 적용`,
      )
      setAskDay(false)
    } catch (err) {
      showToast(err instanceof Error ? err.message : '일괄 적용에 실패했습니다.', true)
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (busy) return
    setBusy(true)
    try {
      await api.deleteNote(photoId)
      setNote(null)
      setText('')
      setEditing(false)
      showToast('메모 삭제됨')
    } catch (err) {
      showToast(err instanceof Error ? err.message : '메모 삭제에 실패했습니다.', true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="note-editor">
      {toast && (
        <div className={`toast${toast.error ? '' : ' toast-info'}`} role="status">
          {toast.message}
        </div>
      )}
      {askDay && date && (
        <div className="note-askday">
          <span>{date} 다른 사진에도 남길까요?</span>
          <div className="note-askday-actions">
            <button type="button" disabled={busy} onClick={applyToDay}>
              같은 날 전체
            </button>
            <button type="button" disabled={busy} onClick={() => setAskDay(false)}>
              이 사진만
            </button>
          </div>
        </div>
      )}
      {note !== null && !editing ? (
        <button type="button" className="note-view" onClick={() => setEditing(true)}>
          <span className="note-text">{note}</span>
          <span className="note-edit-hint">탭하면 편집</span>
        </button>
      ) : (
        <div className="note-form">
          <textarea
            value={text}
            rows={2}
            maxLength={2000} // 서버 NOTE_MAX_CHARS와 동일 캡(M5 리뷰 I4)
            placeholder="이 사진에 대한 기억을 남겨보세요"
            aria-label="사진 메모"
            disabled={busy}
            onChange={(event) => setText(event.target.value)}
          />
          <div className="note-actions">
            {note !== null && (
              <button type="button" className="note-delete" disabled={busy} onClick={remove}>
                삭제
              </button>
            )}
            <button
              type="button"
              className="note-save"
              disabled={busy || !text.trim()}
              onClick={save}
            >
              {busy ? '…' : '저장'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

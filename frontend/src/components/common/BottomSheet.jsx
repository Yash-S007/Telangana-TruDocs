import { useEffect } from 'react'

export default function BottomSheet({ open, onClose, title, children }) {
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [open])

  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape' && open) onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="bottom-sheet-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="bottom-sheet" role="dialog" aria-modal="true">
        <div className="bottom-sheet-handle">
          <div className="bottom-sheet-handle-bar" />
        </div>
        <div className="bottom-sheet-header">
          <h2 className="bottom-sheet-title">{title}</h2>
          <button className="bottom-sheet-close" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="bottom-sheet-body">{children}</div>
      </div>
    </div>
  )
}

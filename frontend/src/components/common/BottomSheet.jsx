import { useEffect, useEffectEvent } from 'react'

// The history.back() of a sheet just closed with ×. It lands a moment later, so a sheet opened
// meanwhile waits for it; otherwise that late Back would close the new sheet.
let leaving = Promise.resolve()

export default function BottomSheet({ open, onClose, title, children }) {
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [open])

  // The phone's Back button (or a swipe back) closes the sheet instead of leaving the site.
  const onBack = useEffectEvent(() => onClose())
  useEffect(() => {
    if (!open) return
    let live = true
    let pushed = false
    leaving.then(() => {
      if (!live) return
      history.pushState({ sheet: true }, '')
      pushed = true
      window.addEventListener('popstate', onBack)
    })
    return () => {
      live = false
      window.removeEventListener('popstate', onBack)
      if (pushed && history.state?.sheet) {  // closed with × or a tap outside: drop our history entry
        leaving = new Promise((done) => {
          window.addEventListener('popstate', () => done(), { once: true })
          history.back()
        })
      }
    }
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

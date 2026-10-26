import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

const TIPS = [
  'Every result comes live from a Telangana government portal.',
  'Government portals answer at their own pace; busy hours can be slower.',
  'A village\u2019s first map can take up to a minute; after that it opens at once.',
  'Official PDFs open in the preview below; use Download to keep a copy.',
  'Survey and village names are matched as the government lists them.',
  'We ask each portal at most once a second, so many searches at once queue up.',
]

export default function LoaderModal({ visible, onCancel, title = 'Searching the government portal…' }) {
  const [tipIdx, setTipIdx] = useState(0)

  useEffect(() => {
    if (!visible) return
    const id = setInterval(() => setTipIdx((i) => (i + 1) % TIPS.length), 4500)
    return () => clearInterval(id)
  }, [visible])

  if (!visible) return null

  return createPortal(
    <div className="loader-overlay" role="dialog" aria-modal="true" aria-label="Searching">
      <div className="loader-card">
        <button className="loader-close" onClick={onCancel} aria-label="Cancel search">
          ×
        </button>

        <svg width="160" height="80" viewBox="0 0 160 80" fill="none" style={{ margin: '0 auto 4px', display: 'block' }}>
          <path
            d="M10 70 Q40 10 80 40 Q120 70 150 10"
            stroke="var(--primary)"
            strokeWidth="2.5"
            strokeDasharray="400"
            fill="none"
            strokeLinecap="round"
            className="loader-trace-path"
            style={{
              strokeDasharray: 400,
              animation: 'trace-draw 2.4s ease-in-out infinite',
            }}
          />
          <circle cx="80" cy="40" r="5" fill="var(--accent)" style={{ opacity: 0.9 }} />
        </svg>

        <div className="loader-dots">
          <div className="loader-dot" />
          <div className="loader-dot" />
          <div className="loader-dot" />
        </div>

        <p className="loader-title">{title}</p>
        <p className="loader-tip">{TIPS[tipIdx]}</p>
      </div>
    </div>,
    document.body
  )
}

import { Fragment, useEffect, useRef } from 'react'
import { TOOL_GROUPS } from '../../tools.js'

export default function AppHeader({ activeView, onNavigate, onMenuOpen }) {
  const tabsRef = useRef(null)

  // The tab bar scrolls sideways when the tabs don't fit: keep the active one in view.
  useEffect(() => {
    const bar = tabsRef.current
    const tab = bar?.querySelector('.app-nav-tab.active')
    if (!bar || !tab) return
    const over = tab.offsetLeft - bar.scrollLeft < 0 || tab.offsetLeft + tab.offsetWidth - bar.scrollLeft > bar.clientWidth
    if (over) bar.scrollTo({ left: tab.offsetLeft - (bar.clientWidth - tab.offsetWidth) / 2, behavior: 'smooth' })
  }, [activeView])

  return (
    <header className="app-nav">
      <div className="app-nav-brand">
        <div className="app-nav-brand-text">
          <span className="app-nav-tagline">
            <img src="/TruEstate full gold.png" alt="TruEstate" height={32} />
          </span>
        </div>
      </div>

      <nav className="app-nav-tabs" aria-label="Main navigation" ref={tabsRef}>
        {TOOL_GROUPS.map((group, g) => (
          <Fragment key={group.title}>
            {g > 0 && <div className="app-nav-sep" aria-hidden="true" />}
            {group.tools.map((item) => (
              <button
                key={item.id}
                className={`app-nav-tab${g > 0 ? ' app-nav-tab-sm' : ''}${activeView === item.id ? ' active' : ''}`}
                onClick={() => onNavigate(item.id)}
                aria-current={activeView === item.id ? 'page' : undefined}
              >
                <i className={`ti ${item.icon}`} />
                <span>{item.label}</span>
              </button>
            ))}
          </Fragment>
        ))}
      </nav>

      <div className="app-nav-end">
        <button
          className="app-nav-hamburger"
          onClick={onMenuOpen}
          aria-label="Open menu"
        >
          <span />
          <span />
          <span />
        </button>
      </div>
    </header>
  )
}

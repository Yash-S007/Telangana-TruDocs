import { useEffect } from 'react'
import { TOOL_GROUPS } from '../../tools.js'

export default function DrawerMenu({ open, activeView, onNavigate, onClose }) {
  useEffect(() => {
    if (open) document.body.style.overflow = 'hidden'
    else document.body.style.overflow = ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  function NavItem({ item }) {
    return (
      <button
        className={`sidebar-nav-item${activeView === item.id ? ' active' : ''}`}
        onClick={() => { onNavigate(item.id); onClose() }}
      >
        <i className={`ti ${item.icon}`} />
        <span>{item.label}</span>
      </button>
    )
  }

  return (
    <>
      <div className={`drawer-backdrop${open ? ' open' : ''}`} onClick={onClose} />
      <aside className={`sidebar drawer${open ? ' open' : ''}`} aria-hidden={!open}>
        <div className="sidebar-logo" style={{ paddingTop: 20 }}>
          <div className="sidebar-logo-img">
            <span className="sidebar-logo-name">TrueDocs</span>
          </div>
          <span className="sidebar-powered">
            powered by&nbsp;<img src="/TruEstate full gold.png" alt="TruEstate" className="sidebar-truestate" />
          </span>
        </div>

        <nav className="sidebar-nav">
          {TOOL_GROUPS.map((group, g) => (
            <div key={group.title}>
              <div className="sidebar-section-title" style={g > 0 ? { marginTop: 8 } : undefined}>{group.title}</div>
              {group.tools.map((item) => <NavItem key={item.id} item={item} />)}
            </div>
          ))}
        </nav>

        <div className="sidebar-status">
          <span className="sidebar-status-dot" />
          <span>Live government data</span>
        </div>
      </aside>
    </>
  )
}

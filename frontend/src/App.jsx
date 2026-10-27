import { Fragment, useState, useEffect } from 'react'
import AppHeader from './components/layout/AppHeader.jsx'
import DrawerMenu from './components/layout/DrawerMenu.jsx'
import BottomSheet from './components/common/BottomSheet.jsx'
import { LegacyTool } from './legacy/LegacyTools.jsx'
import MarketValueView from './views/MarketValue/MarketValueView.jsx'
import LandDetailsView from './views/LandDetails/LandDetailsView.jsx'
import AdangalView from './views/Adangal/AdangalView.jsx'
import { MAIN_TOOL, TOOLS } from './tools.js'

// Each tool's screen, by id. A tool not listed yet still shows its old form (LegacyTool).
const VIEWS = {
  'market-value': MarketValueView,
  'pattadar-passbook': LandDetailsView,
  adangal: AdangalView,
}

function ToolView({ id }) {
  const View = VIEWS[id]
  return View ? <View /> : <LegacyTool id={id} />
}

const SHEET_TITLES = Object.fromEntries(TOOLS.map((t) => [t.id, t.sheet]))
const EXPLORE_CARDS = TOOLS.filter((t) => t.id !== MAIN_TOOL)

function scrollToSection(id) {
  const el = document.getElementById(id)
  if (!el) return
  const top = el.getBoundingClientRect().top + window.scrollY - 68
  window.scrollTo({ top, behavior: 'smooth' })
}

export default function App() {
  const [activeView, setActiveView] = useState(MAIN_TOOL)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [sheetView, setSheetView]   = useState(null)
  const [isMobile, setIsMobile]     = useState(window.innerWidth < 768)

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const handler = (e) => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  // Update active nav tab based on scroll position (desktop only)
  useEffect(() => {
    if (isMobile) return
    const onScroll = () => {
      // The last section can't scroll up to the header, so at the very bottom it is the active one.
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) {
        setActiveView(TOOLS[TOOLS.length - 1].id)
        return
      }
      const offset = 80
      for (const { id } of [...TOOLS].reverse()) {
        const el = document.getElementById(id)
        if (el && el.getBoundingClientRect().top <= offset) {
          setActiveView(id)
          return
        }
      }
      setActiveView(MAIN_TOOL)
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [isMobile])

  function handleNavigate(id) {
    setActiveView(id)
    if (!isMobile) scrollToSection(id)
  }

  return (
    <div className="app-shell">
      <AppHeader
        activeView={activeView}
        onNavigate={handleNavigate}
        onMenuOpen={() => setDrawerOpen(true)}
      />

      <DrawerMenu
        open={drawerOpen}
        activeView={activeView}
        onNavigate={(id) => {
          setActiveView(id)
          setDrawerOpen(false)
          if (isMobile) {
            // The main tool is already on the mobile page itself (not behind a sheet) — open it there
            // instead of stacking a second sheet on top of what's already showing.
            if (id === MAIN_TOOL) window.scrollTo({ top: 0, behavior: 'smooth' })
            else setSheetView(id)
          } else {
            scrollToSection(id)
          }
        }}
        onClose={() => setDrawerOpen(false)}
      />

      <div className="main-content">
        {isMobile ? (
          <>
            <ToolView id={MAIN_TOOL} />
            <div className="explore-section" style={{ padding: '0 16px 80px' }}>
              {/* City strip decoration */}
              <div className="mobile-city-strip" aria-hidden="true">
                <svg viewBox="0 0 390 72" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
                  <defs>
                    <pattern id="mb-w" width="10" height="13" patternUnits="userSpaceOnUse">
                      <rect x="1.5" y="2"  width="3"   height="4"   fill="#0a3d2e" fillOpacity="0.25" />
                      <rect x="5.5" y="2"  width="3"   height="4"   fill="#0a3d2e" fillOpacity="0.25" />
                      <rect x="1.5" y="8"  width="3"   height="3.5" fill="#0a3d2e" fillOpacity="0.25" />
                      <rect x="5.5" y="8"  width="3"   height="3.5" fill="#0a3d2e" fillOpacity="0.25" />
                    </pattern>
                  </defs>
                  {[
                    { x: 0,   w: 28, h: 32 }, { x: 31,  w: 22, h: 46 }, { x: 56,  w: 28, h: 38 },
                    { x: 87,  w: 24, h: 56 }, { x: 114, w: 20, h: 42 }, { x: 137, w: 32, h: 64 },
                    { x: 172, w: 22, h: 50 }, { x: 197, w: 26, h: 58 }, { x: 226, w: 20, h: 44 },
                    { x: 249, w: 30, h: 62 }, { x: 282, w: 24, h: 52 }, { x: 309, w: 28, h: 42 },
                    { x: 340, w: 22, h: 36 }, { x: 365, w: 25, h: 48 },
                  ].map((b, i) => {
                    const y = 72 - b.h
                    return (
                      <g key={i}>
                        <rect x={b.x + 1} y={y} width={b.w - 2} height={b.h}
                          fill="rgba(10,61,46,0.055)" stroke="rgba(10,61,46,0.13)" strokeWidth="1" />
                        <rect x={b.x + 3} y={y + 6} width={b.w - 6} height={b.h - 10}
                          fill="url(#mb-w)" />
                      </g>
                    )
                  })}
                </svg>
              </div>
              <div className="explore-title">Explore More</div>
              <div className="explore-cards">
                {EXPLORE_CARDS.map((card) => (
                  <button
                    key={card.id}
                    className="explore-card"
                    onClick={() => setSheetView(card.id)}
                    type="button"
                  >
                    <div className="explore-card-icon"><i className={`ti ${card.icon}`} /></div>
                    <div className="explore-card-name">{card.label}</div>
                    <div className="explore-card-desc">{card.desc}</div>
                  </button>
                ))}
              </div>
            </div>

            <BottomSheet
              open={!!sheetView}
              onClose={() => setSheetView(null)}
              title={sheetView ? SHEET_TITLES[sheetView] : ''}
            >
              {sheetView && <ToolView id={sheetView} />}
            </BottomSheet>
          </>
        ) : (
          <div className="single-page">
            <div className="lp-hero">
              {/* Background concentric circles */}
              <div className="lp-hero-circles" aria-hidden="true">
                <div className="lp-hero-circle lp-hero-circle-1" />
                <div className="lp-hero-circle lp-hero-circle-2" />
                <div className="lp-hero-circle lp-hero-circle-3" />
              </div>

              {/* Floating badges — wide screens only */}
              <div className="lp-hero-badge lp-hero-badge-l" aria-hidden="true">
                <div className="lp-hero-badge-icon"><i className="ti ti-shield-check" /></div>
                <div className="lp-hero-badge-text">
                  <strong>Govt. Verified</strong>
                  <span>Live government data</span>
                </div>
              </div>
              <div className="lp-hero-badge lp-hero-badge-r" aria-hidden="true">
                <div className="lp-hero-badge-icon"><i className="ti ti-map-pin" /></div>
                <div className="lp-hero-badge-text">
                  <strong>33 Districts</strong>
                  <span>Statewide coverage</span>
                </div>
              </div>

              {/* Main content */}
              <div className="lp-hero-inner">
                <h1 className="lp-hero-title">
                  Telangana&rsquo;s own <em>property records</em> engine.
                </h1>
                <p className="lp-hero-sub">
                  Search property tax and tax receipts, building permissions, mutation, land records, market values, prohibited lands, survey and village maps, lake FTL maps, and RERA certificates — verified live from GHMC, CDMA, TG-bPASS, CCLA, IGRS, TGRAC, HMDA, and TG-RERA.
                </p>
                <div className="lp-hero-stats">
                  <div className="lp-stat">
                    <em className="lp-stat-num">{TOOLS.length}</em>
                    <span className="lp-stat-label">Live Document Types</span>
                  </div>
                  <div className="lp-stat">
                    <em className="lp-stat-num">33</em>
                    <span className="lp-stat-label">Districts Covered</span>
                  </div>
                  <div className="lp-stat">
                    <em className="lp-stat-num">12,777</em>
                    <span className="lp-stat-label">Villages Statewide</span>
                  </div>
                </div>
              </div>

              {/* City skyline illustration */}
              <div className="lp-hero-city" aria-hidden="true">
                <svg viewBox="0 0 1440 200" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
                  <defs>
                    <pattern id="lp-w" width="12" height="16" patternUnits="userSpaceOnUse">
                      <rect x="1.5" y="2"  width="3.5" height="5"   fill="#0a3d2e" fillOpacity="0.28" />
                      <rect x="7"   y="2"  width="3.5" height="5"   fill="#0a3d2e" fillOpacity="0.28" />
                      <rect x="1.5" y="10" width="3.5" height="4.5" fill="#0a3d2e" fillOpacity="0.28" />
                      <rect x="7"   y="10" width="3.5" height="4.5" fill="#0a3d2e" fillOpacity="0.28" />
                    </pattern>
                  </defs>
                  {[
                    { x: 0,    w: 62,  h: 82  }, { x: 66,   w: 50,  h: 122 }, { x: 120,  w: 64,  h: 102 },
                    { x: 188,  w: 56,  h: 150 }, { x: 248,  w: 46,  h: 110 }, { x: 298,  w: 74,  h: 174 },
                    { x: 376,  w: 52,  h: 134 }, { x: 432,  w: 60,  h: 150 }, { x: 496,  w: 47,  h: 114 },
                    { x: 547,  w: 70,  h: 160 }, { x: 621,  w: 55,  h: 140 }, { x: 680,  w: 76,  h: 188 },
                    { x: 760,  w: 51,  h: 147 }, { x: 815,  w: 61,  h: 164 }, { x: 880,  w: 49,  h: 127 },
                    { x: 933,  w: 72,  h: 178 }, { x: 1009, w: 57,  h: 144 }, { x: 1070, w: 63,  h: 160 },
                    { x: 1137, w: 49,  h: 122 }, { x: 1190, w: 70,  h: 168 }, { x: 1264, w: 56,  h: 140 },
                    { x: 1324, w: 49,  h: 110 }, { x: 1377, w: 63,  h: 124 },
                  ].map((b, i) => {
                    const y = 200 - b.h
                    return (
                      <g key={i}>
                        <rect x={b.x + 1} y={y} width={b.w - 2} height={b.h}
                          fill="rgba(10,61,46,0.055)" stroke="rgba(10,61,46,0.13)" strokeWidth="1" />
                        <rect x={b.x + 5} y={y + 10} width={b.w - 10} height={b.h - 18}
                          fill="url(#lp-w)" />
                      </g>
                    )
                  })}
                </svg>
              </div>
            </div>

            {TOOLS.map((tool, i) => (
              <Fragment key={tool.id}>
                {i > 0 && <div className="tool-sep" />}
                <section id={tool.id} className="tool-section">
                  <ToolView id={tool.id} />
                </section>
              </Fragment>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

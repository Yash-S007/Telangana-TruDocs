import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import VillageSearch from '../../components/common/VillageSearch.jsx'
import StatusMessage from '../../components/common/StatusMessage.jsx'
import LoaderModal from '../../components/common/LoaderModal.jsx'
import DocumentResult from '../../components/common/DocumentResult.jsx'
import { lookupVillageMap } from '../../utils/api.js'
import { MAP_H, MAP_W, merc } from '../../utils/mapGeometry.js'
import { useRequest } from '../../utils/useRequest.js'

const VILLAGE_ZOOMS = [1, 2, 4, 8]
// Esri's ready-made 256-pixel photo tiles load in ~0.1 s each; one big exported picture of a
// whole village took 4-23 s and never came at 4096 pixels. (shortcut: Esri's keyless imagery is
// fine for testing; confirm its commercial terms or swap in a licensed provider before going live.)
const SATELLITE_TILES = 'https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/tile'
const WORLD = 20037508.34 // half the Web Mercator world, in metres

// The photo level whose pixels match `screenPx` device pixels across the frame: 18 is ~0.6 m a
// pixel, the sharpest Esri holds for much of rural Telangana.
function tileLevel(box, screenPx) {
  return Math.max(1, Math.min(18, Math.ceil(Math.log2((2 * WORLD * screenPx) / ((box[2] - box[0]) * 256)))))
}

// The tiles covering `part` of the frame ([left, top, right, bottom] as fractions), in drawing units.
function tilesFor(box, part, level) {
  const size = (2 * WORLD) / 2 ** level
  const [w, h] = [box[2] - box[0], box[3] - box[1]]
  const [x0, x1] = [box[0] + part[0] * w, box[0] + part[2] * w]
  const [top, bottom] = [box[3] - part[1] * h, box[3] - part[3] * h]
  const tiles = []
  for (let tx = Math.floor((x0 + WORLD) / size); tx <= Math.floor((x1 + WORLD) / size); tx++) {
    for (let ty = Math.floor((WORLD - top) / size); ty <= Math.floor((WORLD - bottom) / size); ty++) {
      tiles.push({
        key: `${level}/${ty}/${tx}`,
        x: ((tx * size - WORLD - box[0]) / w) * MAP_W,
        y: ((box[3] - (WORLD - ty * size)) / h) * MAP_H,
        w: (size / w) * MAP_W * 1.004, // a hair wider, so no seam shows between tiles
        h: (size / h) * MAP_H * 1.004,
      })
    }
  }
  return tiles
}

// A whole village on the satellite photo: every parcel's outline, and each survey number as big
// as its parcel allows. Small numbers appear as you zoom in; they're drawn, so they stay sharp.
function VillageMap({ result }) {
  const [zoom, setZoom] = useState(1)
  const [shownWidth, setShownWidth] = useState(MAP_W)
  const [view, setView] = useState([0, 0, 1, 1]) // the visible part of the map, as fractions
  const scroller = useRef(null)
  const centre = useRef([0.5, 0.5])
  const settle = useRef(null)

  const drawn = useMemo(() => {
    let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity]
    for (const p of result.parcels) {
      for (const ring of p.rings) {
        for (const ll of ring) {
          const [x, y] = merc(ll)
          x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y)
        }
      }
    }
    // Frame the village with a little room, at the drawing's 4:3 shape.
    const pad = Math.max(x1 - x0, y1 - y0) * 0.03
    let halfW = (x1 - x0) / 2 + pad
    let halfH = (y1 - y0) / 2 + pad
    if (halfW / halfH < MAP_W / MAP_H) halfW = (halfH * MAP_W) / MAP_H
    else halfH = (halfW * MAP_H) / MAP_W
    const box = [(x0 + x1) / 2 - halfW, (y0 + y1) / 2 - halfH, (x0 + x1) / 2 + halfW, (y0 + y1) / 2 + halfH]
    const toPx = (ll) => {
      const [x, y] = merc(ll)
      return [((x - box[0]) / (box[2] - box[0])) * MAP_W, ((box[3] - y) / (box[3] - box[1])) * MAP_H]
    }
    const parcels = result.parcels.map((p) => {
      const rings = p.rings.map((r) => r.map(toPx))
      const px = rings.flat().map((q) => q[0])
      const py = rings.flat().map((q) => q[1])
      const [w, h] = [Math.max(...px) - Math.min(...px), Math.max(...py) - Math.min(...py)]
      return {
        d: rings.map((r) => `M${r.map((q) => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join('L')}Z`).join(''),
        no: p.survey_no,
        x: (Math.min(...px) + Math.max(...px)) / 2,
        y: (Math.min(...py) + Math.max(...py)) / 2,
        size: Math.min(14, 0.45 * h, (0.85 * w) / (0.6 * Math.max(p.survey_no.length, 1))),
      }
    })
    return { box, parcels }
  }, [result])

  function look() {
    const el = scroller.current
    setView([el.scrollLeft / el.scrollWidth, el.scrollTop / el.scrollHeight,
      (el.scrollLeft + el.clientWidth) / el.scrollWidth, (el.scrollTop + el.clientHeight) / el.scrollHeight])
  }
  useEffect(() => {
    const el = scroller.current
    const watch = new ResizeObserver(() => { setShownWidth(el.clientWidth); look() })
    watch.observe(el)
    return () => { watch.disconnect(); clearTimeout(settle.current) }
  }, [])
  // Keep the same spot in the middle while zooming, then fetch sharp photo for what's on screen.
  useLayoutEffect(() => {
    const el = scroller.current
    el.scrollLeft = centre.current[0] * el.scrollWidth - el.clientWidth / 2
    el.scrollTop = centre.current[1] * el.scrollHeight - el.clientHeight / 2
    look()
  }, [zoom])
  function zoomTo(next) {
    const el = scroller.current
    centre.current = [(el.scrollLeft + el.clientWidth / 2) / el.scrollWidth, (el.scrollTop + el.clientHeight / 2) / el.scrollHeight]
    setZoom(next)
  }
  function scrolled() { // once the scrolling stops
    clearTimeout(settle.current)
    settle.current = setTimeout(look, 150)
  }

  const { box } = drawn
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  // A whole-village photo that stays underneath, plus sharper tiles for just the part on screen.
  const baseLevel = tileLevel(box, shownWidth * dpr)
  const sharpLevel = tileLevel(box, shownWidth * zoom * dpr)
  const margin = 0.1 / zoom
  const sharp = sharpLevel > baseLevel
    ? tilesFor(box, [view[0] - margin, view[1] - margin, view[2] + margin, view[3] + margin].map((v) => Math.min(1, Math.max(0, v))), sharpLevel)
    : []
  const pxPerUnit = (shownWidth * zoom) / MAP_W
  return (
    <figure className="village-map">
      <div className="village-map-scroll" ref={scroller} onScroll={scrolled}>
        <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} style={{ width: `${zoom * 100}%` }} role="img" aria-label={`Satellite map of ${result.village} village with its survey numbers`}>
          {[...tilesFor(box, [0, 0, 1, 1], baseLevel), ...sharp].map((t) => (
            <image key={t.key} href={`${SATELLITE_TILES}/${t.key}`} x={t.x} y={t.y} width={t.w} height={t.h} preserveAspectRatio="none" />
          ))}
          {drawn.parcels.map((p, i) => <path key={i} d={p.d} className={p.no ? 'lot' : 'lot road'} />)}
          {drawn.parcels.map((p, i) => {
            // Shown once it would be at least 7px on screen; never bigger than 18px when zoomed in.
            const size = Math.min(p.size, 18 / pxPerUnit)
            return p.no && p.size * pxPerUnit >= 7 && (
              <text key={i} x={p.x} y={p.y} fontSize={size} strokeWidth={size * 0.22}>{p.no}</text>
            )
          })}
        </svg>
      </div>
      <div className="zoom-controls">
        <button type="button" onClick={() => zoomTo(zoom / 2)} disabled={zoom === VILLAGE_ZOOMS[0]} aria-label="Zoom out">−</button>
        <span>{zoom}×</span>
        <button type="button" onClick={() => zoomTo(zoom * 2)} disabled={zoom === VILLAGE_ZOOMS[VILLAGE_ZOOMS.length - 1]} aria-label="Zoom in">+</button>
      </div>
      <figcaption>Imagery: Esri, Vantor, Earthstar Geographics · Boundaries: TGRAC village maps</figcaption>
    </figure>
  )
}

// The A3 PDF in the preview, then what a PDF can't do: the map to zoom into.
function VillageMapResult({ result }) {
  const surveys = result.parcels.filter((p) => p.survey_no).length
  const older = result.map_version === '2.5m'
  return (
    <DocumentResult first={result.doc}>
      {() => (
        <div className="card result-card map-card">
          <h3 className="result-heading">{result.village}, {result.mandal}, {result.district} · {surveys} survey numbers</h3>
          <VillageMap result={result} />
          <p className="result-note">
            {older && 'This village is only on the older map, so outlines can sit 20–50 m from the real spot. '}
            Zoom in to read the survey numbers in crowded areas. Traced from digitised government village maps; for reference only, not a legal survey.
          </p>
        </div>
      )}
    </DocumentResult>
  )
}

export default function VillageMapView() {
  const request = useRequest()
  const { result, busy, error, cancel, fail, reset } = request
  const [village, setVillage] = useState(null)

  function submit(e) {
    e.preventDefault()
    if (!village) { fail('Please select a village first.'); return }
    request.run((signal) => lookupVillageMap(village.dmv, { signal }))
  }

  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-badge">
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#1a6b4a', display: 'inline-block' }} />
          Land survey
        </div>
        <h1 className="page-title">Village Map</h1>
        <p className="page-subtitle">
          A whole village’s survey map on a satellite photo, with every survey number, to view or download as a PDF.
        </p>
        <ul className="page-features">
          <li>Every parcel and survey number, on the satellite photo</li>
          <li>Zoom in to read crowded areas</li>
          <li>Download an A3 PDF of the whole village</li>
        </ul>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <form onSubmit={submit}>
          <div className="field">
            <label>Village / Mandal <span className="req">*</span><span className="field-hint">A village’s first map can take up to a minute</span></label>
            <VillageSearch portal="survey-map" onSelect={(v) => { setVillage(v); reset() }} disabled={busy} />
          </div>
          {error && <div className="field"><StatusMessage kind="error" message={error} /></div>}
          <button type="submit" className="submit-btn" disabled={busy || !village}>
            <i className="ti ti-map-2" /> Show Village Map
          </button>
        </form>
      </div>

      {result && <VillageMapResult key={result.dmv} result={result} />}

      <LoaderModal visible={busy} onCancel={cancel} title="Drawing the village map…" />
    </div>
  )
}

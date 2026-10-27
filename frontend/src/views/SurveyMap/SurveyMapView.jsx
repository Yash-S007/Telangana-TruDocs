import { useRef, useState } from 'react'
import VillageSearch from '../../components/common/VillageSearch.jsx'
import SelectLoading from '../../components/common/SelectLoading.jsx'
import StatusMessage from '../../components/common/StatusMessage.jsx'
import LoaderModal from '../../components/common/LoaderModal.jsx'
import { loadSurveyMapSurveys, loadSurveyParcel } from '../../utils/api.js'
import { MAP_H, MAP_W, merc } from '../../utils/mapGeometry.js'
import { useRequest } from '../../utils/useRequest.js'

// shortcut: Esri's keyless World Imagery (what TGRAC's own viewer uses) is fine for testing;
// before going live, confirm Esri's commercial terms or swap in a licensed provider here.
const SATELLITE_EXPORT = 'https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/export'

function SurveyMap({ result }) {
  // How many times Esri refused the picture; each refusal halves its pixel count.
  const [coarser, setCoarser] = useState(0)
  const own = result.rings.flat().map(merc)
  const xs = own.map((p) => p[0])
  const ys = own.map((p) => p[1])
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  // Frame the parcel with room for its neighbours, at the picture's 4:3 shape.
  const pad = Math.max(x1 - x0, y1 - y0) * 0.6
  // Esri answers HTTP 500 when asked for a picture sharper than it holds for that place:
  // 0.3 m a pixel near Hyderabad, only 0.6 m or coarser in much of rural Telangana. So a small
  // parcel gets at least a 200 m frame, the picture starts at 0.31 m/px, and each refusal
  // retries the same frame with half the pixels (0.62, 1.24, then 2.48 m/px).
  let halfW = Math.max((x1 - x0) / 2 + pad, 100)
  let halfH = (y1 - y0) / 2 + pad
  if (halfW / halfH < MAP_W / MAP_H) halfW = (halfH * MAP_W) / MAP_H
  else halfH = (halfW * MAP_H) / MAP_W
  const box = [(x0 + x1) / 2 - halfW, (y0 + y1) / 2 - halfH, (x0 + x1) / 2 + halfW, (y0 + y1) / 2 + halfH]
  const imageW = Math.round(Math.min(MAP_W * 2, (2 * halfW) / 0.31) / 2 ** coarser)
  const toPx = (lonLat) => {
    const [x, y] = merc(lonLat)
    return [((x - box[0]) / (box[2] - box[0])) * MAP_W, ((box[3] - y) / (box[3] - box[1])) * MAP_H]
  }
  const path = (rings) => rings.map((r) => `M${r.map((p) => toPx(p).map((v) => v.toFixed(1)).join(',')).join('L')}Z`).join('')
  const middle = (rings) => {
    const pts = rings.flat().map(toPx)
    const px = pts.map((p) => p[0])
    const py = pts.map((p) => p[1])
    return [(Math.min(...px) + Math.max(...px)) / 2, (Math.min(...py) + Math.max(...py)) / 2]
  }
  const image = `${SATELLITE_EXPORT}?${new URLSearchParams({
    bbox: box.map((v) => v.toFixed(2)).join(','),
    bboxSR: '3857',
    imageSR: '3857',
    size: `${imageW},${Math.round((imageW * MAP_H) / MAP_W)}`, // up to twice the drawing size, sharp on phones
    format: 'jpg',
    f: 'image',
  })}`
  const [ownX, ownY] = middle(result.rings)
  const labelCorners = result.corners.length <= 20 // beyond that the labels pile on top of each other
  return (
    <figure className="survey-map">
      <svg viewBox={`0 0 ${MAP_W} ${MAP_H}`} role="img" aria-label={`Satellite map of survey number ${result.survey_no}, its boundary and corner points`}>
        <image href={image} width={MAP_W} height={MAP_H} preserveAspectRatio="none"
          onError={() => setCoarser((c) => Math.min(c + 1, 3))} />
        {result.neighbours.map((n, i) => {
          const [lx, ly] = middle(n.rings)
          return (
            <g key={i} className="nb">
              <path d={path(n.rings)} />
              {n.survey_no && <text x={lx} y={ly}>{n.survey_no}</text>}
            </g>
          )
        })}
        <path d={path(result.rings)} className="own-halo" />
        <path d={path(result.rings)} className="own" />
        <text x={ownX} y={ownY} className="own-label">{result.survey_no}</text>
        {result.corners.map((c) => {
          const [px, py] = toPx([c.lon, c.lat])
          return (
            <g key={c.label} className="corner">
              <circle cx={px} cy={py} r="7" />
              {labelCorners && <text x={px + 8} y={py - 8}>{c.label}</text>}
            </g>
          )
        })}
      </svg>
      <figcaption>Imagery: Esri, Vantor, Earthstar Geographics · Boundaries: TGRAC village maps</figcaption>
    </figure>
  )
}

function SurveyMapResult({ result }) {
  const { acres, guntas } = result.area_ac_gts
  const { lat, lon } = result.centre
  const older = result.map_version === '2.5m'
  return (
    <div className="card result-card map-card">
      <StatusMessage kind="success" message={`Survey No. ${result.survey_no} · ${result.village}, ${result.mandal}, ${result.district}`} />
      <SurveyMap key={`${result.village}-${result.survey_no}`} result={result} />
      <dl className="record-fields">
        <div className="record-row">
          <dt>Area (approx.)</dt>
          <dd>{acres} acres {guntas} guntas · {result.area_sq_m.toLocaleString('en-IN')} m²</dd>
        </div>
        {result.remarks && <div className="record-row"><dt>Land note</dt><dd>{result.remarks}</dd></div>}
        <div className="record-row"><dt>Centre</dt><dd>{lat}, {lon}</dd></div>
        <div className="record-row">
          <dt>Map version</dt>
          <dd>{older ? 'Older 2.5 m map' : '30 cm map, matched to sharp satellite imagery'}</dd>
        </div>
      </dl>
      <div className="corner-scroll">
        <table className="corner-table">
          <thead><tr><th>Corner</th><th>Latitude</th><th>Longitude</th></tr></thead>
          <tbody>
            {result.corners.map((c) => (
              <tr key={c.label}><td>{c.label}</td><td>{c.lat}</td><td>{c.lon}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <a className="maps-link" href={`https://www.google.com/maps/search/?api=1&query=${lat},${lon}`} target="_blank" rel="noopener noreferrer">
        <i className="ti ti-map-pin" /> Open in Google Maps
      </a>
      <p className="result-note">
        {older && 'This village is only on the older map, so the outline can sit 20–50 m from the real spot; its shape and area are still a good guide. '}
        Boundary traced from digitised government village maps. Approximate, for reference only, not a legal survey.
      </p>
    </div>
  )
}

export default function SurveyMapView() {
  const request = useRequest()
  const { result, busy, error, cancel, fail, reset } = request
  const [village, setVillage] = useState(null)
  const [surveys, setSurveys] = useState({ loading: false, list: [] })
  const [surveyNo, setSurveyNo] = useState('')
  // A village's first survey list takes 15-25s, so a list for a village the user has since
  // changed must not land under the new one.
  const picked = useRef(null)

  async function onVillage(v) {
    picked.current = v
    setVillage(v)
    setSurveys({ loading: Boolean(v), list: [] })
    setSurveyNo('')
    reset()
    if (!v) return
    try {
      const list = await loadSurveyMapSurveys(v.dmv)
      if (picked.current === v) setSurveys({ loading: false, list })
    } catch (err) {
      if (picked.current === v) { setSurveys({ loading: false, list: [] }); fail(err.message) }
    }
  }

  function submit(e) {
    e.preventDefault()
    if (!village) { fail('Please select a village first.'); return }
    if (!surveyNo) { fail('Please choose the survey number.'); return }
    request.run((signal) => loadSurveyParcel(village.dmv, surveyNo, { signal }))
  }

  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-badge">
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#1a6b4a', display: 'inline-block' }} />
          Land survey
        </div>
        <h1 className="page-title">Survey Map</h1>
        <p className="page-subtitle">
          A survey number’s boundary on a satellite map, with its corner GPS points and area, by village and survey number.
        </p>
        <ul className="page-features">
          <li>Government village maps from TGRAC</li>
          <li>Corner GPS points and the area in acres and guntas</li>
          <li>Open the spot in Google Maps</li>
        </ul>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <form onSubmit={submit}>
          <div className="field">
            <label>Village / Mandal <span className="req">*</span></label>
            <VillageSearch portal="survey-map" onSelect={onVillage} disabled={busy} />
          </div>
          <div className="field">
            <label>Survey Number <span className="req">*</span>{surveys.loading && <span className="field-hint">A village’s first look-up can take up to a minute</span>}</label>
            <SelectLoading loading={surveys.loading} value={surveyNo} onChange={(e) => { setSurveyNo(e.target.value); reset() }} disabled={!village || busy}>
              <option value="">{surveys.loading ? 'Loading survey numbers…' : village ? 'Select survey number' : 'Select village first'}</option>
              {surveys.list.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </SelectLoading>
          </div>
          {error && <div className="field"><StatusMessage kind="error" message={error} /></div>}
          <button type="submit" className="submit-btn" disabled={busy || !village || !surveyNo}>
            <i className="ti ti-map-search" /> Show Survey Map
          </button>
        </form>
      </div>

      {result && <SurveyMapResult result={result} />}

      <LoaderModal visible={busy} onCancel={cancel} title="Drawing the survey map…" />
    </div>
  )
}

import { useEffect, useState } from 'react'
import SelectLoading from '../../components/common/SelectLoading.jsx'
import StatusMessage from '../../components/common/StatusMessage.jsx'
import LoaderModal from '../../components/common/LoaderModal.jsx'
import DocumentResult from '../../components/common/DocumentResult.jsx'
import { findLakes, lakeDocumentPath, loadLakePlaces, lookupLake } from '../../utils/api.js'
import { useRequest } from '../../utils/useRequest.js'

const MODES = [
  { value: 'village', label: 'Village' },
  { value: 'name', label: 'Lake name or lake ID' },
]

// The government's survey of the village's water bodies. It has no HMDA lake IDs, so it can't
// say which one is this lake: the user matches it by survey number, size or place on the map.
function WaterBodies({ village, rows }) {
  if (!rows.length) return null
  return (
    <div className="card result-card">
      <h3 className="result-heading">Water bodies in {village}: encroachment survey</h3>
      <p className="result-note water-note">
        From the government’s Tank Information System (satellite survey of 2023, and 2011 inside the Outer Ring Road).
        It doesn’t use HMDA’s lake IDs, so a water body here may not be this lake: match it by survey number, size or place on the map.
      </p>
      <ul className="doc-list">
        {rows.map((w, i) => (
          <li className="doc-item" key={i}>
            <div className="doc-text">
              <span className="doc-label">{w.name || 'Unnamed water body'} · {w.acres} acres{w.survey_no ? ` · Survey no. ${w.survey_no}` : ''}</span>
              <span className="doc-meta">{w.status_2011 ? `2011: ${w.status_2011} → ` : ''}2023: {w.status_2023}</span>
            </div>
            <a className="table-action-btn" href={`https://www.google.com/maps?q=${w.lat},${w.lon}`} target="_blank" rel="noopener noreferrer">Map&nbsp;↗</a>
          </li>
        ))}
      </ul>
    </div>
  )
}

function LakeResult({ lake }) {
  const facts = [
    ['Lake ID', lake.id],
    ['Village', [lake.village, lake.mandal, lake.district].filter(Boolean).join(', ')],
    ['Preliminary notification', lake.preliminary],
    ['Final notification', lake.final || 'Not issued yet: the FTL boundary is still preliminary'],
  ].filter(([, v]) => v)
  return (
    <>
      <DocumentResult
        first={lake.doc}
        docs={lake.documents.map((d) => ({ key: d.kind, label: d.label, path: lakeDocumentPath(lake.key, d.kind) }))}
        title={lake.name}
        facts={facts}
        note="From HMDA’s lakes portal. The maps are scans: check the survey-number list or the map to see whether a plot is inside the FTL or buffer zone."
        loadingText="Getting the map from HMDA…"
        emptyText="Found, but HMDA holds no maps for this lake."
      />
      <WaterBodies village={lake.village} rows={lake.water_bodies} />
    </>
  )
}

export default function HydraFtlView() {
  const find = useRequest()
  const lookup = useRequest()
  const [mode, setMode] = useState('village')
  const [places, setPlaces] = useState({ loading: true, list: [] })
  const [place, setPlace] = useState({ district: '', mandal: '', village: '' })
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState('')
  const busy = find.busy || lookup.busy
  const { fail } = find

  useEffect(() => {
    loadLakePlaces()
      .then((list) => setPlaces({ loading: false, list }))
      .catch((err) => { setPlaces({ loading: false, list: [] }); fail(err.message) })
  }, [fail])

  function clear() {
    find.reset()
    lookup.reset()
    setPicked('')
  }

  const mandals = places.list.find((d) => d.district === place.district)?.mandals || []
  const villages = mandals.find((m) => m.mandal === place.mandal)?.villages || []
  const pick = (key) => (e) => {
    const value = e.target.value
    setPlace(key === 'district' ? { district: value, mandal: '', village: '' } : key === 'mandal' ? { ...place, mandal: value, village: '' } : { ...place, village: value })
    clear()
  }

  function submit(e) {
    e.preventDefault()
    lookup.reset()  // a new search: the old lake's maps go
    setPicked('')
    if (mode === 'village') {
      if (!place.village) { find.fail('Please select the district, mandal and village.'); return }
      find.run((signal) => findLakes(place, { signal }))
    } else {
      const text = q.trim()
      if (text.length < 2) { find.fail('Type at least 2 letters of the lake’s name, or its lake ID.'); return }
      find.run((signal) => findLakes({ q: text }, { signal }))
    }
  }

  function show(key) {
    setPicked(key)
    lookup.run((signal) => lookupLake(key, { signal }))
  }

  const found = find.result
  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-badge">
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#1a6b4a', display: 'inline-block' }} />
          HMDA Lakes
        </div>
        <h1 className="page-title">Hydra FTL Map</h1>
        <p className="page-subtitle">
          A lake’s official Full Tank Level (FTL) and buffer-zone maps from HMDA, the survey numbers inside them, and the government’s survey of encroached water bodies in the lake’s village.
        </p>
        <ul className="page-features">
          <li>Official FTL and buffer zone maps from HMDA’s lakes portal</li>
          <li>The survey numbers inside the FTL and buffer zone</li>
          <li>Encroachment survey of the village’s water bodies</li>
        </ul>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <div className="field">
          <StatusMessage kind="info" message="Lakes HMDA has notified around Hyderabad (7 districts). The buffer zone is 30 m from the FTL for lakes over 10 hectares, 9 m for smaller ones." />
        </div>
        <div className="field">
          <label>Search By <span className="req">*</span></label>
          <div className="radio-group" role="radiogroup" aria-label="Search by">
            {MODES.map((m) => (
              <label key={m.value} className={`radio-option${mode === m.value ? ' selected' : ''}`}>
                <input type="radio" name="hydra-mode" value={m.value} checked={mode === m.value} disabled={busy}
                  onChange={() => { setMode(m.value); clear() }} />
                {m.label}
              </label>
            ))}
          </div>
        </div>
        <form onSubmit={submit}>
          {mode === 'village' ? (
            <>
              <div className="field">
                <label>District <span className="req">*</span></label>
                <SelectLoading loading={places.loading} value={place.district} onChange={pick('district')} disabled={busy}>
                  <option value="">{places.loading ? 'Loading districts…' : 'Select district'}</option>
                  {places.list.map((d) => <option key={d.district} value={d.district}>{d.district}</option>)}
                </SelectLoading>
              </div>
              <div className="field">
                <label>Mandal <span className="req">*</span></label>
                <SelectLoading loading={false} value={place.mandal} onChange={pick('mandal')} disabled={!place.district || busy}>
                  <option value="">Select mandal</option>
                  {mandals.map((m) => <option key={m.mandal} value={m.mandal}>{m.mandal}</option>)}
                </SelectLoading>
              </div>
              <div className="field">
                <label>Village <span className="req">*</span></label>
                <SelectLoading loading={false} value={place.village} onChange={pick('village')} disabled={!place.mandal || busy}>
                  <option value="">Select village</option>
                  {villages.map((v) => <option key={v} value={v}>{v}</option>)}
                </SelectLoading>
              </div>
            </>
          ) : (
            <div className="field">
              <label>Lake name or lake ID <span className="req">*</span><span className="field-hint">As on HMDA’s list, e.g. Erra Cheruvu or 1025</span></label>
              <input type="text" placeholder="e.g. Erra Cheruvu" value={q} maxLength={80} autoComplete="off" disabled={busy}
                onChange={(e) => { setQ(e.target.value); clear() }} />
            </div>
          )}
          {find.error && <div className="field"><StatusMessage kind="error" message={find.error} /></div>}
          <button type="submit" className="submit-btn" disabled={busy}>
            <i className="ti ti-ripple" /> Find Lakes
          </button>
        </form>
      </div>

      {found && (
        <div className="card result-card">
          <StatusMessage kind="success" message={found.shown < found.total
            ? `Showing ${found.shown} of ${found.total} lakes. Type more of the name to narrow it down.`
            : `${found.total} lake${found.total === 1 ? '' : 's'} found`} />
          <ul className="doc-list">
            {found.lakes.map((l) => (
              <li className="doc-item" key={l.key}>
                <div className="doc-text">
                  <span className="doc-label">{l.name}</span>
                  <span className="doc-meta">
                    Lake ID {l.id} · {l.village}, {l.mandal} · {l.final ? `Final notification ${l.final}` : `Preliminary notification ${l.preliminary}`}
                  </span>
                </div>
                <button type="button" className="table-action-btn" disabled={busy || (picked === l.key && Boolean(lookup.result))} onClick={() => show(l.key)}>
                  {picked === l.key && lookup.result ? 'Showing' : 'Show FTL map'}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {picked && lookup.error && <StatusMessage kind="error" message={lookup.error} />}
      {picked && lookup.result && <LakeResult key={lookup.result.key} lake={lookup.result} />}

      <LoaderModal visible={busy} onCancel={() => { find.cancel(); lookup.cancel() }}
        title={lookup.busy ? 'Getting the FTL map from HMDA…' : 'Finding lakes on HMDA’s list…'} />
    </div>
  )
}

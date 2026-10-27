import { useEffect, useState } from 'react'
import VillageSearch from '../../components/common/VillageSearch.jsx'
import SelectLoading from '../../components/common/SelectLoading.jsx'
import StatusMessage from '../../components/common/StatusMessage.jsx'
import LoaderModal from '../../components/common/LoaderModal.jsx'
import DocumentResult from '../../components/common/DocumentResult.jsx'
import { loadHyderabadDivisions, marketValuePdf, searchHyderabadLocalities } from '../../utils/api.js'
import { useRequest } from '../../utils/useRequest.js'

const AREAS = [
  { value: 'village', label: 'Outside Hyderabad' },
  { value: 'hyderabad', label: 'Hyderabad (GHMC)' },
]

function VillageFields({ request }) {
  const [village, setVillage] = useState(null)

  function submit(e) {
    e.preventDefault()
    if (!village) { request.fail('Please select a village first.'); return }
    request.run((signal) => marketValuePdf({
      district_id: village.district_id,
      mandal_id: village.mandal_id,
      mandal: village.mandal,
      village_id: village.village_id,
      village: village.village,
    }, { signal }))
  }

  return (
    <form onSubmit={submit}>
      <div className="field">
        <label>Village / Mandal <span className="req">*</span></label>
        <VillageSearch portal="market-value" onSelect={(v) => { setVillage(v); request.reset() }} disabled={request.busy} />
      </div>
      {request.error && <div className="field"><StatusMessage kind="error" message={request.error} /></div>}
      <button type="submit" className="submit-btn" disabled={request.busy || !village}>
        <i className="ti ti-currency-rupee" /> Get Market Value
      </button>
    </form>
  )
}

// Hyderabad has no village list on the portal: pick a division, then a locality found by its
// first 3+ letters.
function HyderabadFields({ request }) {
  const [divisions, setDivisions] = useState({ loading: true, list: [] })
  const [divisionId, setDivisionId] = useState('')
  const [locQuery, setLocQuery] = useState('')
  const [localityIndex, setLocalityIndex] = useState('')
  // Localities are stored with the division|text they were fetched for, so a stale reply never
  // shows and "loading" just means no reply yet for what's typed.
  const [fetched, setFetched] = useState({ key: '', list: [] })
  const { fail, reset } = request

  const q = locQuery.trim()
  const searchKey = divisionId && q.length >= 3 ? `${divisionId}|${q}` : ''
  const localities = fetched.key === searchKey ? fetched.list : []
  const locLoading = searchKey !== '' && fetched.key !== searchKey

  useEffect(() => {
    loadHyderabadDivisions()
      .then((list) => setDivisions({ loading: false, list }))
      .catch((err) => { setDivisions({ loading: false, list: [] }); fail(err.message) })
  }, [fail])

  // The portal searches Hyderabad localities by name (3+ letters), so look them up shortly
  // after the user stops typing.
  useEffect(() => {
    if (!searchKey) return
    const ctrl = new AbortController()
    const t = setTimeout(async () => {
      let list = []
      try {
        list = await searchHyderabadLocalities(divisionId, q, { signal: ctrl.signal })
      } catch (err) {
        if (err.name === 'AbortError') return
        fail(err.message)
      }
      setFetched({ key: searchKey, list })
    }, 500)
    return () => { clearTimeout(t); ctrl.abort() }
  }, [searchKey, divisionId, q, fail])

  function submit(e) {
    e.preventDefault()
    const loc = localityIndex !== '' && localities[Number(localityIndex)]
    if (!loc) { fail('Please pick a locality from the list.'); return }
    request.run((signal) => marketValuePdf({
      district_id: '16_1',
      division_id: divisionId,
      locality_id: loc.value,
      locality: loc.label,
    }, { signal }))
  }

  return (
    <form onSubmit={submit}>
      <div className="field">
        <label>Division <span className="req">*</span></label>
        <SelectLoading loading={divisions.loading} value={divisionId} disabled={request.busy}
          onChange={(e) => { setDivisionId(e.target.value); setLocalityIndex(''); reset() }}>
          <option value="">{divisions.loading ? 'Loading divisions…' : 'Select division'}</option>
          {divisions.list.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
        </SelectLoading>
      </div>
      <div className="field">
        <label>Locality name <span className="req">*</span><span className="field-hint">First 3+ letters of the name</span></label>
        <input
          type="text"
          placeholder={divisionId ? 'e.g. Ameerpet' : 'Select division first'}
          value={locQuery}
          onChange={(e) => { setLocQuery(e.target.value); setLocalityIndex(''); reset() }}
          disabled={!divisionId || request.busy}
          autoComplete="off"
        />
      </div>
      <div className="field">
        <label>Locality <span className="req">*</span></label>
        <SelectLoading loading={locLoading} value={localityIndex} disabled={localities.length === 0 || request.busy}
          onChange={(e) => { setLocalityIndex(e.target.value); reset() }}>
          <option value="">
            {locLoading ? 'Searching localities…' : localities.length > 0 ? 'Select locality' : searchKey ? `No locality starts with "${q}"` : 'Type a locality name above'}
          </option>
          {localities.map((l, i) => <option key={i} value={String(i)}>{l.label}</option>)}
        </SelectLoading>
      </div>
      {request.error && <div className="field"><StatusMessage kind="error" message={request.error} /></div>}
      <button type="submit" className="submit-btn" disabled={request.busy || localityIndex === ''}>
        <i className="ti ti-currency-rupee" /> Get Market Value
      </button>
    </form>
  )
}

export default function MarketValueView() {
  const [area, setArea] = useState('village')
  const request = useRequest()
  const { result, busy, cancel } = request

  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-badge">
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#1a6b4a', display: 'inline-block' }} />
          Registration dept
        </div>
        <h1 className="page-title">Land Market Value</h1>
        <p className="page-subtitle">
          Official government land rates (₹ per sq. yard) by village, or by locality in Hyderabad, as used for stamp duty and registration.
        </p>
        <ul className="page-features">
          <li>Live from IGRS, the Registration department</li>
          <li>Every village outside Hyderabad, and Hyderabad by locality</li>
          <li>Land rate and its effective date, as on the official page</li>
        </ul>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <div className="field">
          <label>Area <span className="req">*</span></label>
          <div className="radio-group" role="radiogroup" aria-label="Area">
            {AREAS.map((a) => (
              <label key={a.value} className={`radio-option${area === a.value ? ' selected' : ''}`}>
                <input type="radio" name="mv-area" value={a.value} checked={area === a.value} disabled={busy}
                  onChange={() => { setArea(a.value); request.reset() }} />
                {a.label}
              </label>
            ))}
          </div>
        </div>
        {area === 'village' ? <VillageFields request={request} /> : <HyderabadFields request={request} />}
      </div>

      {result && <DocumentResult key={result.filename} first={result} />}

      <LoaderModal visible={busy} onCancel={cancel} title="Fetching land rates from IGRS…" />
    </div>
  )
}

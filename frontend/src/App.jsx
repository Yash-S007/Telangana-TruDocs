import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import './App.css'

// ---------- shared API hook ----------
// Every failure becomes a sentence a user can act on: the server's own message when it
// sent one, otherwise a plain explanation (never "Failed to fetch" or "[object Object]").
async function errorMessage(res) {
  const data = await res.json().catch(() => ({}))
  if (typeof data.detail === 'string' && data.detail) return data.detail
  if (res.status === 429) return 'Too many searches right now. Please wait a minute and try again.'
  if (res.status >= 500) return "The government portal isn't responding right now. Please try again in a few minutes."
  return 'Please check the details you entered and try again.'
}

function useApi() {
  async function request(path, options) {
    let res
    try {
      res = await fetch(path, options)
    } catch {
      throw new Error("Can't reach TruDocs right now. Please check your internet connection and try again.")
    }
    if (!res.ok) throw new Error(await errorMessage(res))
    return res.json().catch(() => ({}))
  }
  const post = (path, body) => request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const get = (path) => request(path)
  return { post, get }
}

// Shared loading/error/result state for every form — removes repeated boilerplate.
function useFormState() {
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  // Only the latest search may set the result: a reply for an older one is dropped.
  const generation = useRef(0)

  async function run(fn) {
    const gen = ++generation.current
    setError('')
    setResult(null)
    setLoading(true)
    try {
      const data = await fn()
      if (gen === generation.current) setResult(data)
    } catch (err) {
      if (gen === generation.current) setError(err.message)
    } finally {
      if (gen === generation.current) setLoading(false)
    }
  }

  // Clear the result when the inputs change, so it never shows under the wrong search.
  function reset() {
    generation.current++
    setResult(null)
    setError('')
    setLoading(false)
  }

  return { result, error, loading, run, setError, reset }
}

// ---------- field label prettifier ----------
const KNOWN_FIELD_LABELS = {
  ptinno: 'PTIN Number',
  owner: 'Owner Name',
  door: 'Door Number',
  assessmentnum: 'Assessment Number',
}

function fieldLabel(key) {
  const stripped = key
    .replace(/^(grd_SearchResult_|ContentPlaceHolder1_)/i, '')
    .replace(/^lbl/i, '')
    .replace(/_\d+$/, '')
  const known = KNOWN_FIELD_LABELS[stripped.toLowerCase()]
  if (known) return known
  const spaced = stripped.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ').trim()
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : key
}

// ---------- reusable components ----------
function ResultBox({ error, result, children }) {
  if (error) {
    return (
      <div className="result error">
        <span className="result-icon">✕</span>
        <span>{error}</span>
      </div>
    )
  }
  if (!result) return null

  const fields = result.raw_fields && Object.entries(result.raw_fields)
  const tables = result.raw_tables_html
  const notFoundMessage = result.not_found_messages?.[0]

  return (
    <div className="result success">
      {result.found ? (
        <p className="result-status found">
          <span className="result-icon">✓</span> Record found
        </p>
      ) : (
        <p className="result-status not-found">{notFoundMessage || 'No record found.'}</p>
      )}

      {result.found && fields && fields.length > 0 && (
        <dl className="field-list">
          {fields.map(([key, value]) => (
            <div className="field-row" key={key}>
              <dt>{fieldLabel(key)}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {result.found && tables && tables.length > 0 && (
        <div className="portal-table-wrapper">
          {tables.map((html, i) => (
            <div key={i} dangerouslySetInnerHTML={{ __html: html }} />
          ))}
        </div>
      )}

      {result.found && result.rows?.length > 0 && <MarketValueTable rows={result.rows} />}
      {result.found && children}
    </div>
  )
}

// Same columns, in the same order, as the official IGRS results page. On phones each
// row becomes a labelled card (stack-on-mobile).
function MarketValueTable({ rows }) {
  return (
    <div className="portal-table-wrapper">
      <table className="stack-on-mobile">
        <thead>
          <tr>
            <th>Ward-Block</th>
            <th>Locality</th>
            <th>Land Value (₹ per sq. yard)</th>
            <th>Effective Date</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td data-label="Ward-Block">{r.ward_block}</td>
              <td data-label="Locality">{r.locality}</td>
              <td data-label="Land Value (₹/sq. yd)">{r.land_rate_per_sq_yard}</td>
              <td data-label="Effective Date">{r.effective_date}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Field({ label, required, hint, children }) {
  return (
    <div className="field">
      <label>
        {label}{required && <span className="req">*</span>}
        {hint && <span className="field-hint">{hint}</span>}
      </label>
      {children}
    </div>
  )
}

// Select with inline loading spinner — used while survey/khata options are
// being fetched from the government portal.
function SelectLoading({ loading, children, ...props }) {
  return (
    <div className="select-wrap">
      <select {...props} disabled={props.disabled || loading}>{children}</select>
      {loading && <span className="select-spinner" />}
    </div>
  )
}

// Village typeahead — single input that searches the pre-scraped hierarchy.
// All four IDs (district, division, mandal, village) are returned to the
// parent via onSelect so the final search call has everything it needs.
function VillageSearch({ portal, onSelect }) {
  const { get } = useApi()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [showDrop, setShowDrop] = useState(false)
  const [selected, setSelected] = useState(null)
  const [searching, setSearching] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setShowDrop(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    if (selected) return
    if (query.length < 2) { setResults([]); setShowDrop(false); return }
    setSearching(true)
    const t = setTimeout(async () => {
      try {
        const data = await get(`/api/${portal}/villages/search?q=${encodeURIComponent(query)}`)
        setResults(data)
        setShowDrop(true)
      } catch {}
      finally { setSearching(false) }
    }, 300)
    return () => { clearTimeout(t); setSearching(false) }
  }, [query, portal, selected])

  function pick(v) {
    setSelected(v)
    setQuery(`${v.village} — ${v.mandal}, ${v.district}`)
    setResults([])
    setShowDrop(false)
    onSelect(v)
  }

  function clear(e) {
    if (selected) {
      setSelected(null)
      onSelect(null)
      setQuery('')
      setResults([])
      setShowDrop(false)
    } else {
      setQuery(e.target.value)
      onSelect(null)
    }
  }

  function clearAll() {
    setSelected(null)
    onSelect(null)
    setQuery('')
    setResults([])
    setShowDrop(false)
  }

  return (
    <div className="village-search" ref={ref}>
      <div className="village-input-wrap">
        <i className="ti ti-map-pin village-search-icon" />
        <input
          type="text"
          value={query}
          onChange={clear}
          onFocus={() => { if (results.length > 0) setShowDrop(true) }}
          placeholder="Type village name…"
          autoComplete="off"
        />
        {searching && <span className="village-spinner" />}
        {(query && !searching) && (
          <button type="button" className="village-clear" onClick={clearAll} tabIndex={-1}>
            <i className="ti ti-x" />
          </button>
        )}
      </div>
      {showDrop && (
        <div className="village-dropdown">
          {results.length > 0 ? results.map((v, i) => (
            <button
              key={i}
              type="button"
              className="village-option"
              onMouseDown={(e) => { e.preventDefault(); pick(v) }}
            >
              <span className="v-name"><i className="ti ti-home-2" /> {v.village}</span>
              <span className="v-meta">{v.mandal} &middot; {v.district}</span>
            </button>
          )) : (
            <div className="village-no-results">No villages found for "{query}"</div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------- document forms ----------
function MutationForm() {
  const { post } = useApi()
  const { result, error, loading, run } = useFormState()
  const [assessmentNumber, setAssessmentNumber] = useState('')

  return (
    <form onSubmit={(e) => { e.preventDefault(); run(() => post('/api/ghmc/mutation', { assessment_number: assessmentNumber })) }}>
      <Field label="Assessment Number" required hint="e.g. 1010133899">
        <input
          placeholder="Enter assessment number"
          value={assessmentNumber}
          onChange={(e) => setAssessmentNumber(e.target.value)}
          required
        />
      </Field>
      <button type="submit" disabled={loading} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Checking…</> : 'Check Mutation Status'}
      </button>
      <ResultBox error={error} result={result} />
    </form>
  )
}

function PropertyTaxForm() {
  const { post, get } = useApi()
  const { result, error, loading, run } = useFormState()
  const [circles, setCircles] = useState([])
  const [circle, setCircle] = useState('')
  const [ptin, setPtin] = useState('')

  useEffect(() => {
    get('/api/ghmc/circles').then(setCircles).catch(() => {})
  }, [])

  return (
    <form onSubmit={(e) => { e.preventDefault(); run(() => post('/api/ghmc/property-tax', { circle, ptin })) }}>
      <Field label="Circle" required>
        <select value={circle} onChange={(e) => setCircle(e.target.value)} required>
          <option value="">Select Circle</option>
          {circles.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
      </Field>
      <Field label="PTIN Number" required hint="Property Tax Identification Number">
        <input placeholder="e.g. 1010133899" value={ptin} onChange={(e) => setPtin(e.target.value)} required />
      </Field>
      <button type="submit" disabled={loading} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Checking…</> : 'Check Tax Status'}
      </button>
      <ResultBox error={error} result={result} />
    </form>
  )
}

// "Land Details Search" offers the portal's two public search modes. Each is its own
// sub-form so switching mode remounts and clears the other's state.
function LandDetailsForm() {
  const [mode, setMode] = useState('survey')
  return (
    <>
      <Field label="Search By" required>
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="survey">Survey / Khata number</option>
          <option value="passbook">Passbook number + Aadhaar</option>
        </select>
      </Field>
      {mode === 'survey' ? <SurveySearchForm /> : <PassbookSearchForm />}
    </>
  )
}

function SurveySearchForm() {
  const { post, get } = useApi()
  const { result, error, loading, run, setError, reset } = useFormState()
  const [village, setVillage] = useState(null)
  const [surveyOptions, setSurveyOptions] = useState([])
  const [khataOptions, setKhataOptions] = useState([])
  const [surveyNo, setSurveyNo] = useState('')
  const [khataId, setKhataId] = useState('')
  const [surveyLoading, setSurveyLoading] = useState(false)
  const [khataLoading, setKhataLoading] = useState(false)

  async function onVillage(v) {
    setVillage(v)
    setSurveyOptions([]); setKhataOptions([])
    setSurveyNo(''); setKhataId('')
    reset()
    if (v) {
      setSurveyLoading(true)
      try { setSurveyOptions(await get(`/api/pattadar/survey-options/${encodeURIComponent(v.village_id)}`)) }
      catch (err) { setError(err.message) }
      finally { setSurveyLoading(false) }
    }
  }

  async function onSurvey(value) {
    setSurveyNo(value)
    setKhataOptions([]); setKhataId('')
    reset()
    if (value && village) {
      setKhataLoading(true)
      try { setKhataOptions(await get(`/api/pattadar/khata-options/${encodeURIComponent(village.village_id)}?survey_no=${encodeURIComponent(value)}`)) }
      catch (err) { setError(err.message) }
      finally { setKhataLoading(false) }
    }
  }

  function submit(e) {
    e.preventDefault()
    if (!village) { setError('Please select a village first.'); return }
    run(() => post('/api/pattadar/search', {
      district_id: village.district_id,
      mandal_id: village.mandal_id,
      village_id: village.village_id,
      survey_no: surveyNo,
      khata_id: khataId,
    }))
  }

  return (
    <form onSubmit={submit}>
      <Field label="Village / Mandal" required>
        <VillageSearch portal="pattadar" onSelect={onVillage} />
      </Field>
      <Field
        label="Survey No. / Sub-Division No."
        required
        hint={village && !surveyLoading && surveyOptions.length === 0 ? 'Enter manually' : ''}
      >
        {surveyLoading || surveyOptions.length > 0 ? (
          <SelectLoading loading={surveyLoading} value={surveyNo} onChange={(e) => onSurvey(e.target.value)} disabled={!village} required>
            <option value="">{surveyLoading ? 'Loading surveys…' : 'Select Survey Number'}</option>
            {surveyOptions.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </SelectLoading>
        ) : (
          <input
            placeholder={village ? 'e.g. 123 or 1/2A' : 'Select village first'}
            value={surveyNo}
            onChange={(e) => { setSurveyNo(e.target.value); setKhataOptions([]); setKhataId(''); reset() }}
            disabled={!village}
            required
          />
        )}
      </Field>
      <Field label="Khata Number" required>
        <SelectLoading loading={khataLoading} value={khataId} onChange={(e) => { setKhataId(e.target.value); reset() }} disabled={!surveyNo} required>
          <option value="">{khataLoading ? 'Loading khata numbers…' : 'Select Khata Number'}</option>
          {khataOptions.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </SelectLoading>
      </Field>
      <button type="submit" disabled={loading || !village} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Fetching record…</> : 'Fetch Land Details'}
      </button>
      <ResultBox error={error} result={result} />
    </form>
  )
}

function PassbookSearchForm() {
  const { post } = useApi()
  const { result, error, loading, run, setError, reset } = useFormState()
  const [passbookNo, setPassbookNo] = useState('')
  const [aadhaar, setAadhaar] = useState('')

  function submit(e) {
    e.preventDefault()
    if (!passbookNo.trim()) { setError('Please enter the passbook number.'); return }
    if (!/^\d{4}$/.test(aadhaar)) { setError('Please enter exactly the last 4 digits of the Aadhaar number.'); return }
    run(() => post('/api/pattadar/search-by-passbook', {
      passbook_no: passbookNo.trim(),
      aadhaar_last4: aadhaar,
    }))
  }

  return (
    <form onSubmit={submit}>
      <Field label="Passbook (PPB) Number" required hint="On the land passbook, up to 12 characters">
        <input
          placeholder="e.g. 123456789012"
          value={passbookNo}
          onChange={(e) => { setPassbookNo(e.target.value.replace(/[^A-Za-z0-9]/g, '').slice(0, 12)); reset() }}
          autoComplete="off"
          required
        />
      </Field>
      <Field label="Last 4 digits of Aadhaar" required hint="Of the passbook holder">
        <input
          inputMode="numeric"
          placeholder="e.g. 1234"
          value={aadhaar}
          onChange={(e) => { setAadhaar(e.target.value.replace(/\D/g, '').slice(0, 4)); reset() }}
          autoComplete="off"
          required
        />
      </Field>
      <button type="submit" disabled={loading} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Fetching record…</> : 'Fetch Land Details'}
      </button>
      <ResultBox error={error} result={result} />
    </form>
  )
}

function AdangalForm() {
  const { post, get } = useApi()
  const { result, error, loading, run, setError } = useFormState()
  const [village, setVillage] = useState(null)
  const [surveyOptions, setSurveyOptions] = useState([])
  const [surveyNo, setSurveyNo] = useState('')
  const [surveyLoading, setSurveyLoading] = useState(false)

  async function onVillage(v) {
    setVillage(v)
    setSurveyOptions([]); setSurveyNo('')
    if (v) {
      setSurveyLoading(true)
      try { setSurveyOptions(await get(`/api/adangal/survey-options/${v.village_id}`)) }
      catch {}
      finally { setSurveyLoading(false) }
    }
  }

  function submit(e) {
    e.preventDefault()
    if (!village) { setError('Please select a village first.'); return }
    run(() => post('/api/adangal/search', {
      district_id: village.district_id,
      division_id: village.division_id,
      mandal_id: village.mandal_id,
      village_id: village.village_id,
      survey_or_khata_value: surveyNo,
      option: 'surveyNo',
    }))
  }

  return (
    <form onSubmit={submit}>
      <Field label="Village / Division" required>
        <VillageSearch portal="adangal" onSelect={onVillage} />
      </Field>
      <Field
        label="Survey Number"
        required
        hint={village && !surveyLoading && surveyOptions.length === 0 ? 'Enter manually' : ''}
      >
        {surveyLoading || surveyOptions.length > 0 ? (
          <SelectLoading loading={surveyLoading} value={surveyNo} onChange={(e) => setSurveyNo(e.target.value)} disabled={!village} required>
            <option value="">{surveyLoading ? 'Loading surveys…' : 'Select Survey Number'}</option>
            {surveyOptions.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </SelectLoading>
        ) : (
          <input
            placeholder={village ? 'e.g. 123 or 5A' : 'Select village first'}
            value={surveyNo}
            onChange={(e) => setSurveyNo(e.target.value)}
            disabled={!village}
            required
          />
        )}
      </Field>
      <button type="submit" disabled={loading || !village} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Fetching record…</> : 'Get Adangal'}
      </button>
      <ResultBox error={error} result={result} />
    </form>
  )
}

// Hyderabad has no village list on the portal, so it gets its own form. Each
// form remounts when the area changes, which clears the other one's state.
function MarketValueForm() {
  const [area, setArea] = useState('village')

  return (
    <>
      <Field label="Area" required>
        <select value={area} onChange={(e) => setArea(e.target.value)}>
          <option value="village">Outside Hyderabad: search by village</option>
          <option value="hyderabad">Hyderabad (GHMC): search by locality</option>
        </select>
      </Field>
      {area === 'village' ? <VillageMarketValueForm /> : <HyderabadMarketValueForm />}
    </>
  )
}

function VillageMarketValueForm() {
  const { post } = useApi()
  const { result, error, loading, run, setError, reset } = useFormState()
  const [village, setVillage] = useState(null)

  function submit(e) {
    e.preventDefault()
    if (!village) { setError('Please select a village first.'); return }
    run(() => post('/api/market-value/search', {
      district_id: village.district_id,
      mandal_id: village.mandal_id,
      mandal: village.mandal,
      village_id: village.village_id,
      village: village.village,
    }))
  }

  return (
    <form onSubmit={submit}>
      <Field label="Village / Mandal" required>
        <VillageSearch portal="market-value" onSelect={(v) => { setVillage(v); reset() }} />
      </Field>
      <button type="submit" disabled={loading || !village} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Fetching rates…</> : 'Get Market Value'}
      </button>
      <ResultBox error={error} result={result} />
    </form>
  )
}

function HyderabadMarketValueForm() {
  const { post, get } = useApi()
  const { result, error, loading, run, setError, reset } = useFormState()
  const [divisions, setDivisions] = useState([])
  const [divisionId, setDivisionId] = useState('')
  const [locQuery, setLocQuery] = useState('')
  const [localityIndex, setLocalityIndex] = useState('')
  // Localities are stored with the division|text they were fetched for, so a
  // stale reply never shows and "loading" just means no reply yet for what's typed.
  const [fetched, setFetched] = useState({ key: '', list: [] })

  const q = locQuery.trim()
  const searchKey = divisionId && q.length >= 3 ? `${divisionId}|${q}` : ''
  const localities = fetched.key === searchKey ? fetched.list : []
  const locLoading = searchKey !== '' && fetched.key !== searchKey

  useEffect(() => {
    get('/api/market-value/hyderabad/divisions').then(setDivisions).catch((err) => setError(err.message))
  }, [])

  // The portal searches Hyderabad localities by name (3+ letters), so look them
  // up shortly after the user stops typing.
  useEffect(() => {
    if (!searchKey) return
    let cancelled = false
    const t = setTimeout(async () => {
      let list = []
      try {
        list = await get(`/api/market-value/hyderabad/localities?division_id=${encodeURIComponent(divisionId)}&q=${encodeURIComponent(q)}`)
      } catch (err) {
        if (!cancelled) setError(err.message)
      }
      if (!cancelled) setFetched({ key: searchKey, list })
    }, 500)
    return () => { cancelled = true; clearTimeout(t) }
  }, [searchKey])

  function submit(e) {
    e.preventDefault()
    const loc = localityIndex !== '' && localities[Number(localityIndex)]
    if (!loc) { setError('Please pick a locality from the list.'); return }
    run(() => post('/api/market-value/search', {
      district_id: '16_1',
      division_id: divisionId,
      locality_id: loc.value,
      locality: loc.label,
    }))
  }

  return (
    <form onSubmit={submit}>
      <Field label="Division" required>
        <select value={divisionId} onChange={(e) => { setDivisionId(e.target.value); setLocalityIndex(''); reset() }} required>
          <option value="">Select Division</option>
          {divisions.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
        </select>
      </Field>
      <Field label="Locality Name" required hint="First 3+ letters of the name">
        <input
          placeholder={divisionId ? 'e.g. Ameerpet' : 'Select division first'}
          value={locQuery}
          onChange={(e) => { setLocQuery(e.target.value); setLocalityIndex(''); reset() }}
          disabled={!divisionId}
          required
        />
      </Field>
      <Field label="Locality" required>
        <SelectLoading loading={locLoading} value={localityIndex} onChange={(e) => { setLocalityIndex(e.target.value); reset() }} disabled={localities.length === 0} required>
          <option value="">
            {locLoading ? 'Searching localities…' : localities.length > 0 ? 'Select Locality' : searchKey ? `No locality starts with "${q}"` : 'Type a locality name above'}
          </option>
          {localities.map((l, i) => <option key={i} value={String(i)}>{l.label}</option>)}
        </SelectLoading>
      </Field>
      <button type="submit" disabled={loading || localityIndex === ''} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Fetching rates…</> : 'Get Market Value'}
      </button>
      <ResultBox error={error} result={result} />
    </form>
  )
}

const KIND_LABELS = { AGRI: 'Agriculture', NONAGRI: 'Non-Agriculture' }
const SURVEY_ROWS_SHOWN = 200

// "166" + "3" → "166/3". The portal writes "-" or "" for an empty part.
const joinNo = (a, b) => [a, b].filter((x) => x && x !== '-').join('/') || '-'

function ProhibitedLandsForm() {
  const { post, get } = useApi()
  const { result, error, loading, run, setError, reset } = useFormState()
  const [village, setVillage] = useState(null)
  const [sros, setSros] = useState([])
  const [sroCode, setSroCode] = useState('')
  const [sroLoading, setSroLoading] = useState(false)
  // The location the current result belongs to (the village box may have changed since).
  const [searched, setSearched] = useState(null)
  const isHyderabad = village?.district_id === '16_1'

  async function onVillage(v) {
    setVillage(v)
    setSros([]); setSroCode('')
    reset()
    // Hyderabad's entries are divisions, and the portal needs one SRO office picked.
    if (v?.district_id === '16_1') {
      setSroLoading(true)
      try { setSros(await get(`/api/prohibited-lands/hyderabad/sros?division_id=${encodeURIComponent(v.village_id)}`)) }
      catch (err) { setError(err.message) }
      finally { setSroLoading(false) }
    }
  }

  function submit(e) {
    e.preventDefault()
    if (!village) { setError('Please select a village first.'); return }
    if (isHyderabad && !sroCode) { setError('Please select the SRO office.'); return }
    const location = {
      district_id: village.district_id,
      mandal_id: village.mandal_id,
      village_id: village.village_id,
      sro_code: isHyderabad ? sroCode : '',
    }
    setSearched(location)
    run(() => post('/api/prohibited-lands/categories', location))
  }

  return (
    <form onSubmit={submit}>
      <Field label="Village / Mandal" required hint="Hyderabad: type the division, e.g. Secunderabad">
        <VillageSearch portal="prohibited-lands" onSelect={onVillage} />
      </Field>
      {isHyderabad && (
        <Field label="SRO Office" required>
          <SelectLoading loading={sroLoading} value={sroCode} onChange={(e) => { setSroCode(e.target.value); reset() }} required>
            <option value="">{sroLoading ? 'Loading SRO offices…' : 'Select SRO Office'}</option>
            {sros.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </SelectLoading>
        </Field>
      )}
      <button type="submit" disabled={loading || !village || (isHyderabad && !sroCode)} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Checking…</> : 'Check Prohibited Lands'}
      </button>
      <ResultBox error={error} result={result}>
        {result?.categories && searched && <ProhibitedLandsResult location={searched} categories={result.categories} />}
      </ResultBox>
    </form>
  )
}

// One row per 22-A(1) category, one column per land kind, each linking the official PDF.
function ProhibitedLandsResult({ location, categories }) {
  const kinds = Object.keys(categories)
  const labels = categories[kinds[0]].map((c) => c.label)
  const pdfUrl = (kind, formtype) => `/api/prohibited-lands/pdf?${new URLSearchParams({ ...location, kind, formtype })}`

  return (
    <>
      <div className="portal-table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Section 22-A(1)</th>
              {kinds.map((k) => <th key={k}>{KIND_LABELS[k]}</th>)}
            </tr>
          </thead>
          <tbody>
            {labels.map((label) => (
              <tr key={label}>
                <td>{label}</td>
                {kinds.map((k) => {
                  const c = categories[k].find((x) => x.label === label)
                  return (
                    <td key={k}>
                      {c?.available
                        ? <a href={pdfUrl(k, c.formtype)} target="_blank" rel="noopener noreferrer">View&nbsp;PDF&nbsp;↗</a>
                        : 'Not online'}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {kinds.some((k) => categories[k].some((c) => !c.available)) && (
          <p className="field-hint">"Not online": the department doesn't publish these lists on its website.</p>
        )}
      </div>
      {kinds.map((k) => <SurveyList key={k} location={location} kind={k} />)}
    </>
  )
}

// The survey-wise list behind "Court cases & Others". Like the official page, it
// loads every row once and filters in the browser; big areas can take a while.
function SurveyList({ location, kind }) {
  const { post } = useApi()
  const [data, setData] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [filter, setFilter] = useState('')

  useEffect(() => {
    let cancelled = false
    post('/api/prohibited-lands/survey-list', { ...location, kind })
      .then((d) => { if (!cancelled) setData(d) })
      .catch((err) => { if (!cancelled) setLoadError(err.message) })
    return () => { cancelled = true }
  }, [location, kind])

  const q = filter.trim().toUpperCase()
  const matches = !data ? [] : !q ? data.rows : data.rows.filter((r) => [
    joinNo(r.survey_no, r.sub_survey_no), joinNo(r.rev_survey_no, r.rev_sub_survey_no),
    r.door_no, r.ward_block, r.plot_no, r.reason, r.order_no, r.order_date, r.sro,
  ].some((v) => v && v.toUpperCase().includes(q)))
  const shown = matches.slice(0, SURVEY_ROWS_SHOWN)

  return (
    <div className="portal-table-wrapper">
      <p><strong>Survey list: {KIND_LABELS[kind]}</strong>{data && ` (${data.count})`}</p>
      {loadError ? (
        <p>{loadError} Press "Check Prohibited Lands" to try again.</p>
      ) : !data ? (
        <p><span className="inline-spinner" />Loading the survey list… large areas like Hyderabad can take up to a minute.</p>
      ) : data.count === 0 ? (
        <p>No prohibited properties are listed here.</p>
      ) : (
        <>
          <input
            placeholder="Search survey no., door no., plot no., reason…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <p className="field-hint">
            {q ? `${matches.length} of ${data.count} match` : `${data.count} listed`}
            {matches.length > SURVEY_ROWS_SHOWN ? `, showing the first ${SURVEY_ROWS_SHOWN}. Type to narrow down.` : ''}
          </p>
          <div className="survey-scroll">
            <table className="stack-on-mobile">
              <thead>
                <tr>
                  <th>Survey No.</th>
                  <th>Rev. Survey No.</th>
                  <th>Door No.</th>
                  <th>Ward-Block</th>
                  <th>Plot No.</th>
                  <th>Extent (Unit)</th>
                  <th>Reason</th>
                  <th>Order / Notification</th>
                  <th>Volume / Page</th>
                  <th>SRO</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r, i) => (
                  <tr key={i}>
                    <td data-label="Survey No.">{joinNo(r.survey_no, r.sub_survey_no)}</td>
                    <td data-label="Rev. Survey No.">{joinNo(r.rev_survey_no, r.rev_sub_survey_no)}</td>
                    <td data-label="Door No.">{r.door_no}</td>
                    <td data-label="Ward-Block">{r.ward_block}</td>
                    <td data-label="Plot No.">{r.plot_no}</td>
                    <td data-label="Extent">{r.extent}</td>
                    <td data-label="Reason">{r.reason}</td>
                    <td data-label="Order">
                      <span>
                        {r.order_id
                          ? <a href={`/api/prohibited-lands/order?${new URLSearchParams({ order_id: r.order_id, flag: r.order_flag })}`} target="_blank" rel="noopener noreferrer">{r.order_no} ↗</a>
                          : r.order_no}
                        {r.order_date && <><br />{r.order_date}</>}
                      </span>
                    </td>
                    <td data-label="Volume / Page">{r.volume_page}</td>
                    <td data-label="SRO">{r.sro}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

// shortcut: Esri's keyless World Imagery (what TGRAC's own viewer uses) is fine for testing;
// before going live, confirm Esri's commercial terms or swap in a licensed provider here.
const SATELLITE_EXPORT = 'https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/export'
const MAP_W = 640
const MAP_H = 480

// Web Mercator metres, the projection satellite imagery is drawn in.
function merc([lon, lat]) {
  return [(lon * 20037508.34) / 180, Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360)) * 6378137]
}

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
    <div className="result success survey-result">
      <p className="result-status found">
        <span className="result-icon">✓</span> Survey No. {result.survey_no} · {result.village}, {result.mandal}, {result.district}
      </p>
      <SurveyMap key={`${result.village}-${result.survey_no}`} result={result} />
      <dl className="field-list">
        <div className="field-row">
          <dt>Area (approx.)</dt>
          <dd>{acres} acres {guntas} guntas · {result.area_sq_m.toLocaleString('en-IN')} m²</dd>
        </div>
        {result.remarks && (
          <div className="field-row"><dt>Land note</dt><dd>{result.remarks}</dd></div>
        )}
        <div className="field-row"><dt>Centre</dt><dd>{lat}, {lon}</dd></div>
        <div className="field-row">
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
      <p className="survey-note">
        {older && 'This village is only on the older map, so the outline can sit 20–50 m from the real spot; its shape and area are still a good guide. '}
        Boundary traced from digitised government village maps. Approximate, for reference only, not a legal survey.
      </p>
    </div>
  )
}

function SurveyMapForm() {
  const { post, get } = useApi()
  const { result, error, loading, run, setError, reset } = useFormState()
  const [village, setVillage] = useState(null)
  const [surveyOptions, setSurveyOptions] = useState([])
  const [surveyNo, setSurveyNo] = useState('')
  const [surveyLoading, setSurveyLoading] = useState(false)
  // A village's first survey list takes 15-25s, so a list for a village the user has
  // since changed must not land under the new one.
  const picked = useRef(null)

  async function onVillage(v) {
    picked.current = v
    setVillage(v)
    setSurveyOptions([]); setSurveyNo('')
    setSurveyLoading(Boolean(v))
    reset()
    if (!v) return
    try {
      const options = await get(`/api/survey-map/survey-options/${encodeURIComponent(v.dmv)}`)
      if (picked.current === v) setSurveyOptions(options)
    } catch (err) {
      if (picked.current === v) setError(err.message)
    } finally {
      if (picked.current === v) setSurveyLoading(false)
    }
  }

  function submit(e) {
    e.preventDefault()
    if (!village) { setError('Please select a village first.'); return }
    run(() => post('/api/survey-map/parcel', { dmv: village.dmv, survey_no: surveyNo }))
  }

  return (
    <form onSubmit={submit}>
      <Field label="Village / Mandal" required>
        <VillageSearch portal="survey-map" onSelect={onVillage} />
      </Field>
      <Field label="Survey Number" required hint={surveyLoading ? 'A village’s first look-up can take up to a minute' : ''}>
        <SelectLoading loading={surveyLoading} value={surveyNo} onChange={(e) => { setSurveyNo(e.target.value); reset() }} disabled={!village} required>
          <option value="">{surveyLoading ? 'Loading survey numbers…' : village ? 'Select Survey Number' : 'Select village first'}</option>
          {surveyOptions.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
        </SelectLoading>
      </Field>
      <button type="submit" disabled={loading || !village || !surveyNo} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Drawing map…</> : 'Show Survey Map'}
      </button>
      {result ? <SurveyMapResult result={result} /> : <ResultBox error={error} />}
    </form>
  )
}

const VILLAGE_ZOOMS = [1, 2, 4, 8]
// Esri's ready-made 256-pixel photo tiles load in ~0.1 s each; one big exported picture of a
// whole village took 4-23 s and never came at 4096 pixels. (Same Esri licence note as above.)
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

function VillageMapResult({ result }) {
  const surveys = result.parcels.filter((p) => p.survey_no).length
  const older = result.map_version === '2.5m'
  return (
    <div className="result success survey-result">
      <p className="result-status found">
        <span className="result-icon">✓</span> {result.village}, {result.mandal}, {result.district} · {surveys} survey numbers
      </p>
      <VillageMap key={result.dmv} result={result} />
      <div className="map-actions">
        <a className="map-pdf-link" href={`/api/village-map/pdf/${encodeURIComponent(result.dmv)}`} target="_blank" rel="noopener noreferrer">
          <i className="ti ti-file-download" /> Download PDF
        </a>
      </div>
      <p className="survey-note">
        {older && 'This village is only on the older map, so outlines can sit 20–50 m from the real spot. '}
        Zoom in to read the survey numbers in crowded areas. Traced from digitised government village maps; for reference only, not a legal survey.
      </p>
    </div>
  )
}

function VillageMapForm() {
  const { get } = useApi()
  const { result, error, loading, run, setError, reset } = useFormState()
  const [village, setVillage] = useState(null)

  function onVillage(v) {
    setVillage(v)
    reset()
  }

  function submit(e) {
    e.preventDefault()
    if (!village) { setError('Please select a village first.'); return }
    run(() => get(`/api/village-map/map/${encodeURIComponent(village.dmv)}`))
  }

  return (
    <form onSubmit={submit}>
      <Field label="Village / Mandal" required hint="A village’s first map can take up to a minute">
        <VillageSearch portal="survey-map" onSelect={onVillage} />
      </Field>
      <button type="submit" disabled={loading || !village} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Drawing village map…</> : 'Show Village Map'}
      </button>
      {result ? <VillageMapResult result={result} /> : <ResultBox error={error} />}
    </form>
  )
}

const CERTIFICATE_LABELS = {
  registration: 'Registration certificate',
  extension: 'Extension certificate',
  'special-extension': '4-month extension',
}

function ReraResults({ result }) {
  const { total, shown, projects } = result
  return (
    <div className="result success">
      <p className="result-status found">
        <span className="result-icon">✓</span>
        {shown < total
          ? `Showing ${shown} of ${total} projects. Add more words to narrow it down.`
          : `${total} project${total === 1 ? '' : 's'} found`}
      </p>
      <ul className="rera-list">
        {projects.map((p, i) => (
          <li className="rera-item" key={i}>
            <div className="rera-name">{p.project}</div>
            <div className="rera-meta">{p.promoter} · updated {p.last_modified}</div>
            <div className="rera-links">
              {p.certificates.map((c) => (
                <a key={c.kind} className="rera-link primary" target="_blank" rel="noopener noreferrer"
                  href={`/api/rera/certificate?${new URLSearchParams({ kind: c.kind, token: c.token })}`}>
                  {CERTIFICATE_LABELS[c.kind]}&nbsp;↗
                </a>
              ))}
              {p.details_url && (
                <a className="rera-link" href={p.details_url} target="_blank" rel="noopener noreferrer">Project details&nbsp;↗</a>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ReraForm() {
  const { post } = useApi()
  const { result, error, loading, run, setError, reset } = useFormState()
  const [fields, setFields] = useState({ project_name: '', promoter_name: '', registration_no: '' })
  const set = (key) => (e) => { setFields({ ...fields, [key]: e.target.value }); reset() }

  function submit(e) {
    e.preventDefault()
    if (!Object.values(fields).some((v) => v.trim())) {
      setError('Enter a project name, promoter name or registration number.')
      return
    }
    run(() => post('/api/rera/search', fields))
  }

  return (
    <form onSubmit={submit}>
      <Field label="Project name" hint="Fill any one box">
        <input placeholder="e.g. Avasa Hills" value={fields.project_name} onChange={set('project_name')} maxLength={100} />
      </Field>
      <Field label="Promoter / builder name">
        <input placeholder="e.g. YBR Infra" value={fields.promoter_name} onChange={set('promoter_name')} maxLength={50} />
      </Field>
      <Field label="RERA registration number">
        <input placeholder="e.g. P02400001224" value={fields.registration_no} onChange={set('registration_no')} maxLength={15} autoCapitalize="characters" />
      </Field>
      <button type="submit" disabled={loading} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Searching RERA…</> : 'Find RERA Certificate'}
      </button>
      {result ? <ReraResults result={result} /> : <ResultBox error={error} />}
    </form>
  )
}

const rupees = (n) => (n == null ? '-' : `₹${Number(n).toLocaleString('en-IN')}`)

function CdmaTaxResult({ result }) {
  const { ptin, property, dues, receipts } = result
  const receiptUrl = (r) => `/api/cdma-tax/receipt?${new URLSearchParams({ ptin, receipt_no: r.receipt_no, slno: r.slno })}`
  const dueRows = dues && [
    ['Arrear tax', dues.arrear_tax], ['Arrear interest', dues.arrear_interest],
    ['Current tax', dues.current_tax], ['Current interest', dues.current_interest],
    // shown only when the portal charges them, so the rows always add up to the total
    ...[['Cheque bounce penalty', dues.cheque_bounce_penalty], ['Deviation penalty', dues.deviation_penalty],
      ['Adjustment from earlier years', dues.adjustment]].filter(([, v]) => v),
  ]
  return (
    <div className="result success">
      <p className="result-status found">
        <span className="result-icon">✓</span> PTIN {ptin}{property?.town ? ` · ${property.town}` : ''}
      </p>
      <div className="result-actions">
        <a className="map-pdf-link" href={`/api/cdma-tax/pdf/${encodeURIComponent(ptin)}`} target="_blank" rel="noopener noreferrer">
          <i className="ti ti-file-download" /> Download PDF
        </a>
      </div>
      {property && (
        <dl className="field-list">
          {[['Owner', property.owner], ['Door number', property.door_no], ['Locality', property.locality], ['Usage', property.usage]].map(([k, v]) => (
            <div className="field-row" key={k}><dt>{k}</dt><dd>{v || '-'}</dd></div>
          ))}
        </dl>
      )}
      {dues && (
        <>
          <p className="result-subhead">Tax due as on {dues.as_on}</p>
          <dl className="field-list">
            {dueRows.map(([k, v]) => <div className="field-row" key={k}><dt>{k}</dt><dd>{rupees(v)}</dd></div>)}
            <div className="field-row total"><dt>Total due</dt><dd>{rupees(dues.total)}</dd></div>
          </dl>
        </>
      )}
      <p className="result-subhead">{receipts.length ? `${receipts.length} tax receipt${receipts.length === 1 ? '' : 's'}` : 'No tax receipts on the portal for this PTIN yet'}</p>
      {receipts.length > 0 && (
        <>
          <ul className="rera-list receipt-list">
            {receipts.map((r, i) => (
              <li className="rera-item" key={i}>
                <div className="rera-name">{rupees(r.amount)} paid on {r.date}</div>
                <div className="rera-meta">Period {r.paid_from} to {r.paid_to} · {r.mode} · Receipt no. {r.receipt_no}</div>
                <div className="rera-links">
                  {r.slno
                    ? <a className="rera-link primary" href={receiptUrl(r)} target="_blank" rel="noopener noreferrer">Official receipt PDF&nbsp;↗</a>
                    : <span className="rera-meta">This receipt isn’t online</span>}
                </div>
              </li>
            ))}
          </ul>
          <p className="survey-note">The portal can take a minute or more to make each receipt; the PDF opens in a new tab.</p>
        </>
      )}
    </div>
  )
}

function CdmaPtinForm() {
  const { post } = useApi()
  const { result, error, loading, run, setError, reset } = useFormState()
  const [ptin, setPtin] = useState('')

  function submit(e) {
    e.preventDefault()
    if (!/^\d{10}$/.test(ptin)) { setError('A PTIN is 10 digits. You can find it on an old tax receipt or notice.'); return }
    run(() => post('/api/cdma-tax/property', { ptin }))
  }

  return (
    <form onSubmit={submit}>
      <Field label="PTIN Number" required hint="10 digits, on any old tax receipt or notice">
        <input
          inputMode="numeric"
          placeholder="e.g. 1113300005"
          value={ptin}
          onChange={(e) => { setPtin(e.target.value.replace(/\D/g, '').slice(0, 10)); reset() }}
          autoComplete="off"
        />
      </Field>
      <button type="submit" disabled={loading} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Fetching receipts…</> : 'Show Tax Receipts'}
      </button>
      {result ? <CdmaTaxResult result={result} /> : <ResultBox error={error} />}
    </form>
  )
}

function CdmaFindForm() {
  const { post, get } = useApi()
  const find = useFormState()
  const lookup = useFormState()
  const [towns, setTowns] = useState([])
  const [fields, setFields] = useState({ town_id: '', door_no: '', owner_name: '' })
  const [picked, setPicked] = useState('')
  const set = (key) => (e) => { setFields({ ...fields, [key]: e.target.value }); find.reset(); lookup.reset(); setPicked('') }

  useEffect(() => {
    get('/api/cdma-tax/towns').then(setTowns).catch(() => {})
  }, [])

  function submit(e) {
    e.preventDefault()
    const door = fields.door_no.trim()
    const owner = fields.owner_name.trim()
    if (!fields.town_id) { find.setError('Please select the town.'); return }
    if (!door && !owner) { find.setError('Enter a door number or the owner’s name.'); return }
    if ((door && door.length < 3) || (owner && owner.length < 3)) { find.setError('Please enter at least 3 characters.'); return }
    find.run(() => post('/api/cdma-tax/find', fields))
  }

  function show(ptin) {
    setPicked(ptin)
    lookup.run(() => post('/api/cdma-tax/property', { ptin }))
  }

  const found = find.result
  return (
    <form onSubmit={submit}>
      <Field label="Town" required>
        <select value={fields.town_id} onChange={set('town_id')}>
          <option value="">Select town</option>
          {towns.map((d) => (
            <optgroup key={d.district_id} label={d.district}>
              {d.towns.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </optgroup>
          ))}
        </select>
      </Field>
      <Field label="Door number" hint="Fill any one box">
        <input placeholder="e.g. 8-1-43" value={fields.door_no} onChange={set('door_no')} maxLength={30} autoComplete="off" />
      </Field>
      <Field label="Owner name">
        <input placeholder="As on the tax records" value={fields.owner_name} onChange={set('owner_name')} maxLength={50} autoComplete="off" />
      </Field>
      <button type="submit" disabled={find.loading} className={find.loading ? 'btn-loading' : ''}>
        {find.loading ? <><span className="btn-spinner" /> Searching…</> : 'Find Property'}
      </button>
      {found ? (
        <div className="result success">
          <p className="result-status found">
            <span className="result-icon">✓</span>
            {found.shown < found.total
              ? `Showing ${found.shown} of ${found.total} properties. Add more to narrow it down.`
              : `${found.total} propert${found.total === 1 ? 'y' : 'ies'} found`}
          </p>
          <ul className="rera-list">
            {found.properties.map((p) => (
              <li className="rera-item" key={p.ptin}>
                <div className="rera-name">{p.owner}</div>
                <div className="rera-meta">Door {p.door_no} · {p.locality} · PTIN {p.ptin}</div>
                <div className="rera-links">
                  <button type="button" className="rera-link primary" disabled={lookup.loading} onClick={() => show(p.ptin)}>
                    {lookup.loading && picked === p.ptin ? 'Fetching receipts…' : 'Show tax receipts'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : <ResultBox error={find.error} />}
      {picked && (lookup.result ? <CdmaTaxResult result={lookup.result} /> : <ResultBox error={lookup.error} />)}
    </form>
  )
}

function CdmaTaxForm() {
  const [mode, setMode] = useState('ptin')
  return (
    <>
      <Field label="Search By" required>
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="ptin">PTIN number</option>
          <option value="find">Door number or owner name</option>
        </select>
      </Field>
      {mode === 'ptin' ? <CdmaPtinForm /> : <CdmaFindForm />}
    </>
  )
}

// ---------- page structure ----------
const DOCUMENT_TYPES = [
  {
    id: 'ghmc-mutation',
    icon: 'ti ti-home-2',
    navLabel: 'GHMC Mutation',
    tag: 'Municipality',
    heading: 'GHMC Mutation Status',
    description: 'Check the latest ownership mutation status for a Hyderabad property by assessment number.',
    Form: MutationForm,
  },
  {
    id: 'ghmc-property-tax',
    icon: 'ti ti-receipt',
    navLabel: 'GHMC Property Tax',
    tag: 'Municipality',
    heading: 'GHMC Property Tax',
    description: 'Search property tax records by PTIN number within a GHMC circle.',
    Form: PropertyTaxForm,
  },
  {
    id: 'cdma-tax-receipt',
    icon: 'ti ti-receipt-2',
    navLabel: 'CDMA Tax Receipt',
    tag: 'Municipality',
    heading: 'Property Tax Receipt (CDMA)',
    description: 'Property tax receipts, tax due and owner details for any Telangana town outside Hyderabad, by PTIN or by door number or owner name. Each receipt downloads as the official PDF.',
    Form: CdmaTaxForm,
  },
  {
    id: 'pattadar-passbook',
    icon: 'ti ti-id-badge-2',
    navLabel: 'Land Details Search',
    tag: 'Revenue dept',
    heading: 'Land Details Search',
    description: 'Agricultural land status and ownership from Bhu Bharati — by village + survey/khata number, or by passbook number and the last 4 digits of the owner’s Aadhaar.',
    Form: LandDetailsForm,
  },
  {
    id: 'adangal',
    icon: 'ti ti-map-2',
    navLabel: 'Adangal (Pahani)',
    tag: 'Revenue dept',
    heading: 'Adangal Extract (Pahani)',
    description: 'Land ownership, cultivation, and usage record for agricultural land by village and survey number.',
    Form: AdangalForm,
  },
  {
    id: 'market-value',
    icon: 'ti ti-currency-rupee',
    navLabel: 'Market Value',
    tag: 'Registration dept',
    heading: 'Land Market Value',
    description: 'Official government land rates (₹ per sq. yard) by village, or by locality in Hyderabad, as used for stamp duty and registration.',
    Form: MarketValueForm,
  },
  {
    id: 'prohibited-lands',
    icon: 'ti ti-ban',
    navLabel: 'Prohibited Lands (22A)',
    tag: 'Registration dept',
    heading: 'Prohibited Lands (Section 22A)',
    description: 'Official lists of properties barred from registration under Section 22-A, for agricultural and non-agricultural land by village, with the government orders behind each entry.',
    Form: ProhibitedLandsForm,
  },
  {
    id: 'survey-map',
    icon: 'ti ti-map-search',
    navLabel: 'Survey Map',
    tag: 'Land survey',
    heading: 'Survey Map',
    description: 'A survey number’s boundary on a satellite map, with its corner GPS points and area, by village and survey number.',
    Form: SurveyMapForm,
  },
  {
    id: 'village-map',
    icon: 'ti ti-map-2',
    navLabel: 'Village Map',
    tag: 'Land survey',
    heading: 'Village Map',
    description: 'A whole village’s survey map on a satellite photo, with every survey number, to view or download as a PDF.',
    Form: VillageMapForm,
  },
  {
    id: 'rera-certificate',
    icon: 'ti ti-certificate',
    navLabel: 'RERA Certificate',
    tag: 'TG-RERA',
    heading: 'RERA Certificate',
    description: 'The official RERA registration certificate of a real estate project (and its extensions), by project, promoter or registration number.',
    Form: ReraForm,
  },
]

function Skyline() {
  const buildings = [40, 60, 30, 75, 45, 90, 55, 35, 70, 50, 65, 38, 80, 42]
  return (
    <svg className="skyline" viewBox="0 0 700 90" preserveAspectRatio="none" fill="none">
      {buildings.map((h, i) => (
        <rect key={i} x={i * 50 + 5} y={90 - h} width="36" height={h} fill="currentColor" opacity="0.5" />
      ))}
    </svg>
  )
}

export default function App() {
  const [activeId, setActiveId] = useState(DOCUMENT_TYPES[0].id)

  useEffect(() => {
    const sections = DOCUMENT_TYPES.map((d) => document.getElementById(d.id)).filter(Boolean)
    const lastId = DOCUMENT_TYPES[DOCUMENT_TYPES.length - 1].id
    // The last section can't scroll up into the observer's band, so at the very
    // bottom of the page it is the active one.
    const atBottom = () => window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2
    const observer = new IntersectionObserver(
      (entries) => {
        if (atBottom()) { setActiveId(lastId); return }
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
        if (visible) setActiveId(visible.target.id)
      },
      { rootMargin: '-35% 0px -50% 0px', threshold: [0, 0.25, 0.5, 0.75, 1] }
    )
    sections.forEach((s) => observer.observe(s))
    const onScroll = () => { if (atBottom()) setActiveId(lastId) }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      observer.disconnect()
      window.removeEventListener('scroll', onScroll)
    }
  }, [])

  // On phones the tab bar scrolls sideways; slide it so the active tab stays in view.
  useEffect(() => {
    const nav = document.querySelector('.navbar')
    const tab = nav?.querySelector('.nav-tab.active')
    if (!nav || !tab || nav.scrollWidth <= nav.clientWidth) return
    nav.scrollTo({ left: tab.offsetLeft - (nav.clientWidth - tab.offsetWidth) / 2, behavior: 'smooth' })
  }, [activeId])

  function scrollToSection(id) {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="app">
      <nav className="navbar">
        <div className="brand"><i className="ti ti-building-skyscraper" /> TruDocs Telangana</div>
        <div className="nav-tabs">
          {DOCUMENT_TYPES.map((d) => (
            <button
              key={d.id}
              className={`nav-tab${d.id === activeId ? ' active' : ''}`}
              onClick={() => scrollToSection(d.id)}
            >
              <i className={d.icon} /> {d.navLabel}
            </button>
          ))}
        </div>
      </nav>

      <div className="hero">
        <div className="hero-badge left">
          <div className="icon"><i className="ti ti-shield-check" /></div>
          <div>
            <div className="title">Govt. Verified</div>
            <div className="subtitle">Live government data</div>
          </div>
        </div>
        <div className="hero-badge right">
          <div className="icon"><i className="ti ti-map-pin" /></div>
          <div>
            <div className="title">33 Districts</div>
            <div className="subtitle">Statewide coverage</div>
          </div>
        </div>

        <h1>Telangana's own <em>property records</em> engine.</h1>
        <p className="tagline">
          Search property tax and tax receipts, mutation, land records, market values, prohibited lands, survey and village maps, and RERA certificates — verified live from GHMC, CDMA, CCLA, IGRS, TGRAC, and TG-RERA, Telangana.
        </p>

        <div className="stat-bar">
          <div className="stat">
            <span className="num">{DOCUMENT_TYPES.length}</span>
            <span className="label">Live Document Types</span>
          </div>
          <div className="stat">
            <span className="num">33</span>
            <span className="label">Districts Covered</span>
          </div>
          <div className="stat">
            <span className="num">12,777</span>
            <span className="label">Villages Statewide</span>
          </div>
        </div>

        <Skyline />
      </div>

      {DOCUMENT_TYPES.map((d, i) => (
        <div className="search-section" id={d.id} key={d.id}>
          <div className="search-intro">
            <span className="index">{String(i + 1).padStart(2, '0')}</span>
            <span className="pill">{d.tag}</span>
            <h2>{d.heading}</h2>
            <p>{d.description}</p>
          </div>
          <div className="form-card">
            <d.Form />
          </div>
        </div>
      ))}
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
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
function ResultBox({ error, result }) {
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

function PattadarForm() {
  const { post, get } = useApi()
  const { result, error, loading, run, setError } = useFormState()
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
    if (v) {
      setSurveyLoading(true)
      try { setSurveyOptions(await get(`/api/pattadar/survey-options/${v.village_id}`)) }
      catch {}
      finally { setSurveyLoading(false) }
    }
  }

  async function onSurvey(value) {
    setSurveyNo(value)
    setKhataOptions([]); setKhataId('')
    if (value && village) {
      setKhataLoading(true)
      try { setKhataOptions(await get(`/api/pattadar/khata-options/${village.village_id}?survey_no=${encodeURIComponent(value)}`)) }
      catch {}
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
            onChange={(e) => { setSurveyNo(e.target.value); setKhataOptions([]); setKhataId('') }}
            disabled={!village}
            required
          />
        )}
      </Field>
      <Field label="Khata Number" required>
        <SelectLoading loading={khataLoading} value={khataId} onChange={(e) => setKhataId(e.target.value)} disabled={!surveyNo} required>
          <option value="">{khataLoading ? 'Loading khata numbers…' : 'Select Khata Number'}</option>
          {khataOptions.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </SelectLoading>
      </Field>
      <button type="submit" disabled={loading || !village} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Fetching record…</> : 'Fetch Pattadar Details'}
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
    id: 'pattadar-passbook',
    icon: 'ti ti-id-badge-2',
    navLabel: 'Pattadar Passbook',
    tag: 'Revenue dept',
    heading: 'Pattadar Passbook',
    description: 'Land ownership and passbook details by village, survey and khata number.',
    Form: PattadarForm,
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
          Search property tax, mutation, land records, and RERA certificates — verified live from GHMC, CCLA, and TG-RERA, Telangana.
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

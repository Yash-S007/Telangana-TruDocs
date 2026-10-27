import { useRef, useState } from 'react'
import './legacy.css'

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
  async function send(path, options) {
    let res
    try {
      res = await fetch(path, options)
    } catch (err) {
      if (err.name === 'AbortError') throw err
      throw new Error("Can't reach TruDocs right now. Please check your internet connection and try again.")
    }
    if (!res.ok) throw new Error(await errorMessage(res))
    return res
  }
  async function request(path, options) {
    return (await send(path, options)).json().catch(() => ({}))
  }
  // A PDF for the preview: its bytes and the server's filename.
  async function pdf(path, signal) {
    const res = await send(path, { signal })
    const name = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') || '')
    return { blob: await res.blob(), filename: name ? name[1] : 'document.pdf' }
  }
  const post = (path, body) => request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const get = (path) => request(path)
  return { post, get, pdf }
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

// ---------- document forms ----------
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
    id: 'rera-certificate',
    icon: 'ti ti-certificate',
    navLabel: 'RERA Certificate',
    tag: 'TG-RERA',
    heading: 'RERA Certificate',
    description: 'The official RERA registration certificate of a real estate project (and its extensions), by project, promoter or registration number.',
    Form: ReraForm,
  },
]

// The old page's markup for one tool, until it gets its own screen in the new design.
export function LegacyTool({ id }) {
  const d = DOCUMENT_TYPES.find((t) => t.id === id)
  return (
    <div className="legacy">
      <div className="search-section">
        <div className="search-intro">
          <span className="pill">{d.tag}</span>
          <h2>{d.heading}</h2>
          <p>{d.description}</p>
        </div>
        <div className="form-card">
          <d.Form />
        </div>
      </div>
    </div>
  )
}

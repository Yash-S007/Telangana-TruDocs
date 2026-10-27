import { useEffect, useRef, useState } from 'react'
import './legacy.css'
import { downloadBlob, renderPdfToCanvas } from '../utils/pdf.js'

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

// The kit's PDFViewer (trudocs-state/frontend-shell): the PDF's pages on a dark panel, with a download button.
function PdfViewer({ blob, filename }) {
  const containerRef = useRef(null)

  useEffect(() => {
    if (!blob || !containerRef.current) return
    let cancelled = false
    renderPdfToCanvas(blob, containerRef.current, () => cancelled)
    return () => { cancelled = true }
  }, [blob])

  if (!blob) return null
  return (
    <div className="pdf-preview-wrapper">
      <div className="pdf-preview-bar">
        <span className="pdf-preview-label">{filename || 'Preview'}</span>
        <button type="button" className="download-btn" onClick={() => downloadBlob(blob, filename || 'document.pdf')}>
          <i className="ti ti-download" /> Download
        </button>
      </div>
      <div ref={containerRef} className="pdf-canvas-container" />
    </div>
  )
}

// A look-up and its details PDF together, so the result opens with its preview.
async function cdmaLookup({ post, pdf }, ptin) {
  const data = await post('/api/cdma-tax/property', { ptin })
  return { ...data, doc: { key: 'details', ...(await pdf(`/api/cdma-tax/pdf/${encodeURIComponent(ptin)}`)) } }
}

// Like the Karnataka EC tool: one document at a time in the PDF preview, our details PDF first,
// then any official receipt picked from the list underneath.
function CdmaTaxResult({ result }) {
  const { pdf } = useApi()
  const { ptin, property, receipts } = result
  const [doc, setDoc] = useState(result.doc)  // the PDF on show: {key, blob, filename}
  const [loading, setLoading] = useState('')  // key of the document being fetched
  const [error, setError] = useState('')
  const generation = useRef(0)
  const controller = useRef(null)

  useEffect(() => {
    const pending = controller
    return () => pending.current?.abort()  // a receipt still loading when the result goes away
  }, [])

  async function show(key, path) {
    const gen = ++generation.current
    controller.current?.abort()
    controller.current = new AbortController()
    setLoading(key)
    setError('')
    try {
      const file = await pdf(path, controller.current.signal)
      if (gen === generation.current) setDoc({ key, ...file })
    } catch (err) {
      if (gen === generation.current && err.name !== 'AbortError') setError(err.message)
    } finally {
      if (gen === generation.current) setLoading('')
    }
  }

  const receiptPath = (r) => `/api/cdma-tax/receipt?${new URLSearchParams({ ptin, receipt_no: r.receipt_no, slno: r.slno })}`
  const button = (key, path, label) => (
    <button type="button" className="rera-link primary" disabled={Boolean(loading) || doc.key === key} onClick={() => show(key, path)}>
      {loading === key ? <><span className="inline-spinner" />Loading…</> : doc.key === key ? 'Showing' : label}
    </button>
  )
  return (
    <>
      {loading ? (
        <p className="status-msg info">
          <span className="inline-spinner" />
          {loading === 'details' ? 'Preparing the PDF…' : 'Getting the official receipt from the portal. This can take a minute or more…'}
        </p>
      ) : error ? <ResultBox error={error} /> : (
        <p className="status-msg success"><i className="ti ti-circle-check" /> Found! {doc.filename}</p>
      )}
      <div className="pdf-actions">
        <button type="button" className="download-btn" onClick={() => downloadBlob(doc.blob, doc.filename)}>
          <i className="ti ti-download" /> Download PDF
        </button>
        <span className="pdf-meta">{doc.filename}</span>
      </div>
      <PdfViewer blob={doc.blob} filename={doc.filename} />
      <div className="result success documents">
        <p className="result-status found">
          <span className="result-icon">✓</span> PTIN {ptin}{property?.town ? ` · ${property.town}` : ''}
        </p>
        <ul className="rera-list receipt-list">
          <li className="rera-item">
            <div className="rera-name">Property tax details</div>
            <div className="rera-meta">Owner, tax due and every receipt, for reference</div>
            <div className="rera-links">{button('details', `/api/cdma-tax/pdf/${encodeURIComponent(ptin)}`, 'Show details')}</div>
          </li>
          {receipts.map((r, i) => (
            <li className="rera-item" key={i}>
              <div className="rera-name">{rupees(r.amount)} paid on {r.date}</div>
              <div className="rera-meta">Period {r.paid_from} to {r.paid_to} · {r.mode} · Receipt no. {r.receipt_no}</div>
              <div className="rera-links">
                {r.slno ? button(`receipt-${i}`, receiptPath(r), 'Show official receipt') : <span className="rera-meta">This receipt isn’t online</span>}
              </div>
            </li>
          ))}
        </ul>
        <p className="survey-note">
          {receipts.length ? 'The portal can take a minute or more to make each official receipt.' : 'No tax receipts on the portal for this PTIN yet.'}
        </p>
      </div>
    </>
  )
}

function CdmaPtinForm() {
  const api = useApi()
  const { result, error, loading, run, setError, reset } = useFormState()
  const [ptin, setPtin] = useState('')

  function submit(e) {
    e.preventDefault()
    if (!/^\d{10}$/.test(ptin)) { setError('A PTIN is 10 digits. You can find it on an old tax receipt or notice.'); return }
    run(() => cdmaLookup(api, ptin))
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
      {result ? <CdmaTaxResult key={result.ptin} result={result} /> : <ResultBox error={error} />}
    </form>
  )
}

function CdmaFindForm() {
  const api = useApi()
  const { post, get } = api
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
    lookup.run(() => cdmaLookup(api, ptin))
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
      {picked && (lookup.result ? <CdmaTaxResult key={lookup.result.ptin} result={lookup.result} /> : <ResultBox error={lookup.error} />)}
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

const bpassDocPath = (fileNo, kind) => `/api/bpass/document?${new URLSearchParams({ file_no: fileNo, kind })}`

// An application and its main letter together, so the result opens with its preview.
async function bpassLookup({ post, pdf }, fileNo) {
  const data = await post('/api/bpass/application', { file_no: fileNo })
  const first = data.documents[0]
  return { ...data, doc: first ? { key: first.kind, ...(await pdf(bpassDocPath(data.file_no, first.kind))) } : null }
}

// Like the CDMA tool: the official letter in the PDF preview, the application's details, and
// its other letters underneath to switch the preview.
function BpassResult({ result }) {
  const { pdf } = useApi()
  const [doc, setDoc] = useState(result.doc)  // the letter on show: {key, blob, filename}
  const [loading, setLoading] = useState('')  // kind of the letter being fetched
  const [error, setError] = useState('')
  const generation = useRef(0)
  const controller = useRef(null)

  useEffect(() => {
    const pending = controller
    return () => pending.current?.abort()  // a letter still loading when the result goes away
  }, [])

  async function show(kind) {
    const gen = ++generation.current
    controller.current?.abort()
    controller.current = new AbortController()
    setLoading(kind)
    setError('')
    try {
      const file = await pdf(bpassDocPath(result.file_no, kind), controller.current.signal)
      if (gen === generation.current) setDoc({ key: kind, ...file })
    } catch (err) {
      if (gen === generation.current && err.name !== 'AbortError') setError(err.message)
    } finally {
      if (gen === generation.current) setLoading('')
    }
  }

  const facts = [
    ['Status', result.status], ['Approval for', result.approval_for], ['Type', result.type],
    ['Applied on', result.applied_on], ['Decided on', result.decided_on],
    ['Town', [result.town, result.district].filter(Boolean).join(', ')],
    ['Survey / plot', [result.survey_no && `Survey ${result.survey_no}`, result.plot_no && `Plot ${result.plot_no}`].filter(Boolean).join(' · ')],
    ['Locality', result.locality],
  ].filter(([, v]) => v)
  return (
    <>
      {loading ? (
        <p className="status-msg info"><span className="inline-spinner" />Getting the letter from the portal…</p>
      ) : error ? <ResultBox error={error} /> : doc ? (
        <p className="status-msg success"><i className="ti ti-circle-check" /> Found! {doc.filename}</p>
      ) : (
        <p className="status-msg info"><i className="ti ti-info-circle" /> Found, but the portal holds no letters for this application.</p>
      )}
      {doc && (
        <>
          <div className="pdf-actions">
            <button type="button" className="download-btn" onClick={() => downloadBlob(doc.blob, doc.filename)}>
              <i className="ti ti-download" /> Download PDF
            </button>
            <span className="pdf-meta">{doc.filename}</span>
          </div>
          <PdfViewer blob={doc.blob} filename={doc.filename} />
        </>
      )}
      <div className="result success documents">
        <p className="result-status found">
          <span className="result-icon">✓</span> {result.file_no}{result.town ? ` · ${result.town}` : ''}
        </p>
        <dl className="field-list">
          {facts.map(([k, v]) => <div className="field-row" key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
        </dl>
        {result.documents.length > 0 && (
          <ul className="rera-list receipt-list">
            {result.documents.map((d) => (
              <li className="rera-item" key={d.kind}>
                <div className="rera-name">{d.label}</div>
                <div className="rera-links">
                  <button type="button" className="rera-link primary" disabled={Boolean(loading) || doc?.key === d.kind} onClick={() => show(d.kind)}>
                    {loading === d.kind ? <><span className="inline-spinner" />Loading…</> : doc?.key === d.kind ? 'Showing' : 'Show'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="survey-note">From the old TG-bPASS portal: applications filed before December 2025. Newer ones are on BuildNow.</p>
      </div>
    </>
  )
}

function BpassForm() {
  const api = useApi()
  const { result, error, loading, run, setError, reset } = useFormState()
  const [fileNo, setFileNo] = useState('')

  function submit(e) {
    e.preventDefault()
    const value = fileNo.trim().toUpperCase()
    if (!/^[A-Z0-9][A-Z0-9/-]{4,39}$/.test(value)) { setError('Please enter the TG-bPASS file number, as on the permission letter.'); return }
    run(() => bpassLookup(api, value))
  }

  return (
    <form onSubmit={submit}>
      <p className="status-msg info form-notice">
        <i className="ti ti-info-circle" /> Only applications filed on TG-bPASS before December 2025 are available here. Newer ones are on BuildNow.
      </p>
      <Field label="File number" required hint="On the permission letter or acknowledgement">
        <input
          placeholder="e.g. 123456/XXXX/0123/2025"
          value={fileNo}
          onChange={(e) => { setFileNo(e.target.value.replace(/\s/g, '')); reset() }}
          autoComplete="off"
          autoCapitalize="characters"
        />
      </Field>
      <button type="submit" disabled={loading} className={loading ? 'btn-loading' : ''}>
        {loading ? <><span className="btn-spinner" /> Fetching permission…</> : 'Show Building Permission'}
      </button>
      {result ? <BpassResult key={result.file_no} result={result} /> : <ResultBox error={error} />}
    </form>
  )
}

const hydraDocPath = (key, kind) => `/api/hydra-ftl/document?${new URLSearchParams({ key, kind })}`

// A lake and its FTL map together, so the result opens with its preview.
async function hydraLookup({ get, pdf }, key) {
  const data = await get(`/api/hydra-ftl/lake?${new URLSearchParams({ key })}`)
  const first = data.documents[0]
  return { ...data, doc: first ? { key: first.kind, ...(await pdf(hydraDocPath(data.key, first.kind))) } : null }
}

// The government's survey of the village's water bodies. It has no HMDA lake IDs, so it can't
// say which one is this lake: the user matches it by survey number, size or place on the map.
function WaterBodies({ village, rows }) {
  if (!rows.length) return null
  return (
    <div className="result success documents">
      <p className="result-status found">
        <span className="result-icon">✓</span> Water bodies in {village}: encroachment survey
      </p>
      <p className="survey-note">
        From the government’s Tank Information System (satellite survey of 2023, and 2011 inside the Outer Ring Road).
        It doesn’t use HMDA’s lake IDs, so a water body here may not be this lake: match it by survey number, size or place on the map.
      </p>
      <ul className="rera-list receipt-list">
        {rows.map((w, i) => (
          <li className="rera-item" key={i}>
            <div className="rera-name">
              {w.name || 'Unnamed water body'} · {w.acres} acres{w.survey_no ? ` · Survey no. ${w.survey_no}` : ''}
            </div>
            <div className="rera-meta">{w.status_2011 ? `2011: ${w.status_2011} → ` : ''}2023: {w.status_2023}</div>
            <div className="rera-links">
              <a className="rera-link" href={`https://www.google.com/maps?q=${w.lat},${w.lon}`} target="_blank" rel="noopener noreferrer">Map&nbsp;↗</a>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

// Like the TG-bPASS tool: the FTL map in the PDF preview, the lake's details, and its other maps
// underneath to switch the preview; then the village's water bodies.
function HydraResult({ result }) {
  const { pdf } = useApi()
  const [doc, setDoc] = useState(result.doc)  // the map on show: {key, blob, filename}
  const [loading, setLoading] = useState('')  // kind of the map being fetched
  const [error, setError] = useState('')
  const generation = useRef(0)
  const controller = useRef(null)

  useEffect(() => {
    const pending = controller
    return () => pending.current?.abort()  // a map still loading when the result goes away
  }, [])

  async function show(kind) {
    const gen = ++generation.current
    controller.current?.abort()
    controller.current = new AbortController()
    setLoading(kind)
    setError('')
    try {
      const file = await pdf(hydraDocPath(result.key, kind), controller.current.signal)
      if (gen === generation.current) setDoc({ key: kind, ...file })
    } catch (err) {
      if (gen === generation.current && err.name !== 'AbortError') setError(err.message)
    } finally {
      if (gen === generation.current) setLoading('')
    }
  }

  const facts = [
    ['Lake ID', result.id],
    ['Village', [result.village, result.mandal, result.district].filter(Boolean).join(', ')],
    ['Preliminary notification', result.preliminary],
    ['Final notification', result.final || 'Not issued yet: the FTL boundary is still preliminary'],
  ].filter(([, v]) => v)
  return (
    <>
      {loading ? (
        <p className="status-msg info"><span className="inline-spinner" />Getting the map from HMDA…</p>
      ) : error ? <ResultBox error={error} /> : doc ? (
        <p className="status-msg success"><i className="ti ti-circle-check" /> Found! {doc.filename}</p>
      ) : (
        <p className="status-msg info"><i className="ti ti-info-circle" /> Found, but HMDA holds no maps for this lake.</p>
      )}
      {doc && (
        <>
          <div className="pdf-actions">
            <button type="button" className="download-btn" onClick={() => downloadBlob(doc.blob, doc.filename)}>
              <i className="ti ti-download" /> Download PDF
            </button>
            <span className="pdf-meta">{doc.filename}</span>
          </div>
          <PdfViewer blob={doc.blob} filename={doc.filename} />
        </>
      )}
      <div className="result success documents">
        <p className="result-status found">
          <span className="result-icon">✓</span> {result.name}
        </p>
        <dl className="field-list">
          {facts.map(([k, v]) => <div className="field-row" key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
        </dl>
        {result.documents.length > 0 && (
          <ul className="rera-list receipt-list">
            {result.documents.map((d) => (
              <li className="rera-item" key={d.kind}>
                <div className="rera-name">{d.label}</div>
                <div className="rera-links">
                  <button type="button" className="rera-link primary" disabled={Boolean(loading) || doc?.key === d.kind} onClick={() => show(d.kind)}>
                    {loading === d.kind ? <><span className="inline-spinner" />Loading…</> : doc?.key === d.kind ? 'Showing' : 'Show'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="survey-note">From HMDA’s lakes portal. The maps are scans: check the survey-number list or the map to see whether a plot is inside the FTL or buffer zone.</p>
      </div>
      <WaterBodies village={result.village} rows={result.water_bodies} />
    </>
  )
}

function HydraFtlForm() {
  const api = useApi()
  const { get } = api
  const find = useFormState()
  const lookup = useFormState()
  const [mode, setMode] = useState('village')
  const [places, setPlaces] = useState([])
  const [placesLoading, setPlacesLoading] = useState(true)
  const [place, setPlace] = useState({ district: '', mandal: '', village: '' })
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState('')
  const clear = () => { find.reset(); lookup.reset(); setPicked('') }

  useEffect(() => {
    get('/api/hydra-ftl/places').then(setPlaces).catch((err) => find.setError(err.message)).finally(() => setPlacesLoading(false))
  }, [])

  const mandals = places.find((d) => d.district === place.district)?.mandals || []
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
      if (!place.village) { find.setError('Please select the district, mandal and village.'); return }
      find.run(() => get(`/api/hydra-ftl/lakes?${new URLSearchParams(place)}`))
    } else {
      const text = q.trim()
      if (text.length < 2) { find.setError('Type at least 2 letters of the lake’s name, or its lake ID.'); return }
      find.run(() => get(`/api/hydra-ftl/lakes?${new URLSearchParams({ q: text })}`))
    }
  }

  function show(key) {
    setPicked(key)
    lookup.run(() => hydraLookup(api, key))
  }

  const found = find.result
  return (
    <form onSubmit={submit}>
      <p className="status-msg info form-notice">
        <i className="ti ti-info-circle" /> Lakes HMDA has notified around Hyderabad (7 districts). The buffer zone is 30 m from the FTL for lakes over 10 hectares, 9 m for smaller ones.
      </p>
      <Field label="Search By" required>
        <select value={mode} onChange={(e) => { setMode(e.target.value); clear() }}>
          <option value="village">Village</option>
          <option value="name">Lake name or lake ID</option>
        </select>
      </Field>
      {mode === 'village' ? (
        <>
          <Field label="District" required>
            <SelectLoading loading={placesLoading} value={place.district} onChange={pick('district')}>
              <option value="">{placesLoading ? 'Loading districts…' : 'Select district'}</option>
              {places.map((d) => <option key={d.district} value={d.district}>{d.district}</option>)}
            </SelectLoading>
          </Field>
          <Field label="Mandal" required>
            <select value={place.mandal} onChange={pick('mandal')} disabled={!place.district}>
              <option value="">Select mandal</option>
              {mandals.map((m) => <option key={m.mandal} value={m.mandal}>{m.mandal}</option>)}
            </select>
          </Field>
          <Field label="Village" required>
            <select value={place.village} onChange={pick('village')} disabled={!place.mandal}>
              <option value="">Select village</option>
              {villages.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </Field>
        </>
      ) : (
        <Field label="Lake name or lake ID" required hint="As on HMDA’s list, e.g. Erra Cheruvu or 1025">
          <input placeholder="e.g. Erra Cheruvu" value={q} onChange={(e) => { setQ(e.target.value); clear() }} maxLength={80} autoComplete="off" />
        </Field>
      )}
      <button type="submit" disabled={find.loading} className={find.loading ? 'btn-loading' : ''}>
        {find.loading ? <><span className="btn-spinner" /> Finding lakes…</> : 'Find Lakes'}
      </button>
      {found ? (
        <div className="result success">
          <p className="result-status found">
            <span className="result-icon">✓</span>
            {found.shown < found.total
              ? `Showing ${found.shown} of ${found.total} lakes. Type more of the name to narrow it down.`
              : `${found.total} lake${found.total === 1 ? '' : 's'} found`}
          </p>
          <ul className="rera-list">
            {found.lakes.map((l) => (
              <li className="rera-item" key={l.key}>
                <div className="rera-name">{l.name}</div>
                <div className="rera-meta">
                  Lake ID {l.id} · {l.village}, {l.mandal} · {l.final ? `Final notification ${l.final}` : `Preliminary notification ${l.preliminary}`}
                </div>
                <div className="rera-links">
                  <button type="button" className="rera-link primary" disabled={lookup.loading} onClick={() => show(l.key)}>
                    {lookup.loading && picked === l.key ? 'Fetching FTL map…' : 'Show FTL map'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : <ResultBox error={find.error} />}
      {picked && (lookup.result ? <HydraResult key={lookup.result.key} result={lookup.result} /> : <ResultBox error={lookup.error} />)}
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
    id: 'cdma-tax-receipt',
    icon: 'ti ti-receipt-2',
    navLabel: 'CDMA Tax Receipt',
    tag: 'Municipality',
    heading: 'Property Tax Receipt (CDMA)',
    description: 'Property tax receipts, tax due and owner details for any Telangana town outside Hyderabad, by PTIN or by door number or owner name. Each receipt downloads as the official PDF.',
    Form: CdmaTaxForm,
  },
  {
    id: 'building-permission',
    icon: 'ti ti-building',
    navLabel: 'Building Permission',
    tag: 'TG-bPASS',
    heading: 'Building Permission (TG‑bPASS)',  // a non-breaking hyphen keeps TG-bPASS on one line
    description: 'The status of a building permission filed on TG-bPASS before December 2025, and its official letters (permit order, letter of approval to start work), by file number.',
    Form: BpassForm,
  },
  {
    id: 'hydra-ftl-map',
    icon: 'ti ti-ripple',
    navLabel: 'Hydra FTL Map',
    tag: 'HMDA Lakes',
    heading: 'Hydra FTL Map',
    description: 'A lake’s official Full Tank Level (FTL) and buffer-zone maps from HMDA, the survey numbers inside them, and the government’s survey of encroached water bodies in the lake’s village.',
    Form: HydraFtlForm,
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

import { useEffect, useState } from 'react'
import SelectLoading from '../../components/common/SelectLoading.jsx'
import StatusMessage from '../../components/common/StatusMessage.jsx'
import LoaderModal from '../../components/common/LoaderModal.jsx'
import DocumentResult from '../../components/common/DocumentResult.jsx'
import { cdmaDetailsPath, cdmaReceiptPath, findCdmaProperties, loadCdmaTowns, lookupCdmaProperty } from '../../utils/api.js'
import { useRequest } from '../../utils/useRequest.js'

const MODES = [
  { value: 'ptin', label: 'PTIN number' },
  { value: 'find', label: 'Door number or owner name' },
]

const rupees = (n) => (n == null ? '-' : `₹${Number(n).toLocaleString('en-IN')}`)

// Like the Karnataka EC tool: our details PDF first, then any official receipt picked from the list.
function CdmaResult({ result }) {
  const { ptin, property, receipts } = result
  const docs = [
    { key: 'details', label: 'Property tax details', meta: 'Owner, tax due and every receipt, for reference', path: cdmaDetailsPath(ptin),
      button: 'Show details', loadingText: 'Preparing the PDF…' },
    ...receipts.map((r, i) => ({
      key: `receipt-${i}`,
      label: `${rupees(r.amount)} paid on ${r.date}`,
      meta: `Period ${r.paid_from} to ${r.paid_to} · ${r.mode} · Receipt no. ${r.receipt_no}`,
      path: r.slno ? cdmaReceiptPath(ptin, r) : null,
      button: 'Show official receipt',
    })),
  ]
  return (
    <DocumentResult
      first={result.doc}
      docs={docs}
      title={`PTIN ${ptin}${property?.town ? ` · ${property.town}` : ''}`}
      note={receipts.length ? 'The portal can take a minute or more to make each official receipt.' : 'No tax receipts on the portal for this PTIN yet.'}
      loadingText="Getting the official receipt from the portal. This can take a minute or more…"
    />
  )
}

function PtinFields({ lookup }) {
  const [ptin, setPtin] = useState('')
  const { busy, error, fail, reset } = lookup

  function submit(e) {
    e.preventDefault()
    if (!/^\d{10}$/.test(ptin)) { fail('A PTIN is 10 digits. You can find it on an old tax receipt or notice.'); return }
    lookup.run((signal) => lookupCdmaProperty(ptin, { signal }))
  }

  return (
    <form onSubmit={submit}>
      <div className="field">
        <label>PTIN Number <span className="req">*</span><span className="field-hint">10 digits, on any old tax receipt or notice</span></label>
        <input
          type="text"
          inputMode="numeric"
          placeholder="e.g. 1113300005"
          value={ptin}
          onChange={(e) => { setPtin(e.target.value.replace(/\D/g, '').slice(0, 10)); reset() }}
          disabled={busy}
          autoComplete="off"
        />
      </div>
      {error && <div className="field"><StatusMessage kind="error" message={error} /></div>}
      <button type="submit" className="submit-btn" disabled={busy}>
        <i className="ti ti-receipt-2" /> Show Tax Receipts
      </button>
    </form>
  )
}

function FindFields({ find, lookup }) {
  const [towns, setTowns] = useState({ loading: true, list: [] })
  const [fields, setFields] = useState({ town_id: '', door_no: '', owner_name: '' })
  const busy = find.busy || lookup.busy
  const { fail } = find
  const set = (key) => (e) => { setFields({ ...fields, [key]: e.target.value }); find.reset(); lookup.reset() }

  useEffect(() => {
    loadCdmaTowns()
      .then((list) => setTowns({ loading: false, list }))
      .catch((err) => { setTowns({ loading: false, list: [] }); fail(err.message) })
  }, [fail])

  function submit(e) {
    e.preventDefault()
    lookup.reset()
    const door = fields.door_no.trim()
    const owner = fields.owner_name.trim()
    if (!fields.town_id) { find.fail('Please select the town.'); return }
    if (!door && !owner) { find.fail('Enter a door number or the owner’s name.'); return }
    if ((door && door.length < 3) || (owner && owner.length < 3)) { find.fail('Please enter at least 3 characters.'); return }
    find.run((signal) => findCdmaProperties(fields, { signal }))
  }

  return (
    <form onSubmit={submit}>
      <div className="field">
        <label>Town <span className="req">*</span></label>
        <SelectLoading loading={towns.loading} value={fields.town_id} onChange={set('town_id')} disabled={busy}>
          <option value="">{towns.loading ? 'Loading towns…' : 'Select town'}</option>
          {towns.list.map((d) => (
            <optgroup key={d.district_id} label={d.district}>
              {d.towns.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </optgroup>
          ))}
        </SelectLoading>
      </div>
      <div className="field">
        <label>Door number <span className="field-hint">Fill any one box</span></label>
        <input type="text" placeholder="e.g. 8-1-43" value={fields.door_no} onChange={set('door_no')} maxLength={30} autoComplete="off" disabled={busy} />
      </div>
      <div className="field">
        <label>Owner name</label>
        <input type="text" placeholder="As on the tax records" value={fields.owner_name} onChange={set('owner_name')} maxLength={50} autoComplete="off" disabled={busy} />
      </div>
      {find.error && <div className="field"><StatusMessage kind="error" message={find.error} /></div>}
      <button type="submit" className="submit-btn" disabled={busy}>
        <i className="ti ti-search" /> Find Property
      </button>
    </form>
  )
}

export default function CdmaTaxView() {
  const [mode, setMode] = useState('ptin')
  const lookup = useRequest()
  const find = useRequest()
  const [picked, setPicked] = useState('')
  const busy = lookup.busy || find.busy

  function switchMode(value) {
    setMode(value)
    lookup.reset()
    find.reset()
    setPicked('')
  }

  function show(ptin) {
    setPicked(ptin)
    lookup.run((signal) => lookupCdmaProperty(ptin, { signal }))
  }

  const found = mode === 'find' && find.result
  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-badge">
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#1a6b4a', display: 'inline-block' }} />
          Municipality
        </div>
        <h1 className="page-title">Property Tax Receipt (CDMA)</h1>
        <p className="page-subtitle">
          Property tax receipts, tax due and owner details for any Telangana town outside Hyderabad, by PTIN or by door number or owner name. Each receipt downloads as the official PDF.
        </p>
        <ul className="page-features">
          <li>Live from CDMA, every town outside GHMC</li>
          <li>Tax due and every receipt in one PDF</li>
          <li>Each receipt as the official PDF</li>
        </ul>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <div className="field">
          <label>Search By <span className="req">*</span></label>
          <div className="radio-group" role="radiogroup" aria-label="Search by">
            {MODES.map((m) => (
              <label key={m.value} className={`radio-option${mode === m.value ? ' selected' : ''}`}>
                <input type="radio" name="cdma-mode" value={m.value} checked={mode === m.value} disabled={busy}
                  onChange={() => switchMode(m.value)} />
                {m.label}
              </label>
            ))}
          </div>
        </div>
        {mode === 'ptin' ? <PtinFields lookup={lookup} /> : <FindFields find={find} lookup={lookup} />}
      </div>

      {found && (
        <div className="card result-card">
          <StatusMessage kind="success" message={found.shown < found.total
            ? `Showing ${found.shown} of ${found.total} properties. Add more to narrow it down.`
            : `${found.total} propert${found.total === 1 ? 'y' : 'ies'} found`} />
          <ul className="doc-list">
            {found.properties.map((p) => (
              <li className="doc-item" key={p.ptin}>
                <div className="doc-text">
                  <span className="doc-label">{p.owner}</span>
                  <span className="doc-meta">Door {p.door_no} · {p.locality} · PTIN {p.ptin}</span>
                </div>
                <button type="button" className="table-action-btn" disabled={busy || (picked === p.ptin && Boolean(lookup.result))} onClick={() => show(p.ptin)}>
                  {picked === p.ptin && lookup.result ? 'Showing' : 'Show tax receipts'}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {mode === 'find' && picked && lookup.error && <StatusMessage kind="error" message={lookup.error} />}
      {lookup.result && <CdmaResult key={lookup.result.ptin} result={lookup.result} />}

      <LoaderModal visible={busy} onCancel={() => { lookup.cancel(); find.cancel() }}
        title={lookup.busy ? 'Getting the tax receipts from CDMA…' : 'Searching CDMA’s property records…'} />
    </div>
  )
}

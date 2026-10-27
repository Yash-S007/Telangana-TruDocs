import { useEffect, useState } from 'react'
import SelectLoading from '../../components/common/SelectLoading.jsx'
import StatusMessage from '../../components/common/StatusMessage.jsx'
import LoaderModal from '../../components/common/LoaderModal.jsx'
import DocumentResult from '../../components/common/DocumentResult.jsx'
import { ghmcPropertyTaxPdf, loadGhmcCircles } from '../../utils/api.js'
import { useRequest } from '../../utils/useRequest.js'

export default function GhmcPropertyTaxView() {
  const request = useRequest()
  const { result, busy, error, cancel, fail, reset } = request
  const [circles, setCircles] = useState({ loading: true, list: [] })
  const [circle, setCircle] = useState('')
  const [ptin, setPtin] = useState('')

  useEffect(() => {
    loadGhmcCircles()
      .then((list) => setCircles({ loading: false, list }))
      .catch((err) => { setCircles({ loading: false, list: [] }); fail(err.message) })
  }, [fail])

  function submit(e) {
    e.preventDefault()
    if (!circle) { fail('Please select the circle.'); return }
    if (!ptin.trim()) { fail('Please enter the PTIN number.'); return }
    request.run((signal) => ghmcPropertyTaxPdf(circle, ptin.trim(), { signal }))
  }

  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-badge">
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#1a6b4a', display: 'inline-block' }} />
          Municipality
        </div>
        <h1 className="page-title">GHMC Property Tax</h1>
        <p className="page-subtitle">
          Search property tax records by PTIN number within a GHMC circle.
        </p>
        <ul className="page-features">
          <li>Live from GHMC</li>
          <li>Pick the circle, then enter the PTIN</li>
          <li>The tax record as GHMC shows it</li>
        </ul>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <form onSubmit={submit}>
          <div className="field">
            <label>Circle <span className="req">*</span></label>
            <SelectLoading loading={circles.loading} value={circle} onChange={(e) => { setCircle(e.target.value); reset() }} disabled={busy}>
              <option value="">{circles.loading ? 'Loading circles…' : 'Select circle'}</option>
              {circles.list.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </SelectLoading>
          </div>
          <div className="field">
            <label>PTIN Number <span className="req">*</span><span className="field-hint">Property Tax Identification Number</span></label>
            <input
              type="text"
              inputMode="numeric"
              placeholder="e.g. 1010133899"
              value={ptin}
              onChange={(e) => { setPtin(e.target.value.replace(/\D/g, '').slice(0, 10)); reset() }}
              disabled={busy}
              autoComplete="off"
            />
          </div>
          {error && <div className="field"><StatusMessage kind="error" message={error} /></div>}
          <button type="submit" className="submit-btn" disabled={busy}>
            <i className="ti ti-receipt" /> Check Tax Status
          </button>
        </form>
      </div>

      {result && <DocumentResult key={result.filename} first={result} />}

      <LoaderModal visible={busy} onCancel={cancel} title="Checking GHMC property tax…" />
    </div>
  )
}

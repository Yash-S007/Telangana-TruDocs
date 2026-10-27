import { useState } from 'react'
import StatusMessage from '../../components/common/StatusMessage.jsx'
import LoaderModal from '../../components/common/LoaderModal.jsx'
import DocumentResult from '../../components/common/DocumentResult.jsx'
import { ghmcMutationPdf } from '../../utils/api.js'
import { useRequest } from '../../utils/useRequest.js'

export default function GhmcMutationView() {
  const request = useRequest()
  const { result, busy, error, cancel, fail, reset } = request
  const [assessmentNumber, setAssessmentNumber] = useState('')

  function submit(e) {
    e.preventDefault()
    const value = assessmentNumber.trim()
    if (!value) { fail('Please enter the assessment number.'); return }
    request.run((signal) => ghmcMutationPdf(value, { signal }))
  }

  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-badge">
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#1a6b4a', display: 'inline-block' }} />
          Municipality
        </div>
        <h1 className="page-title">GHMC Mutation Status</h1>
        <p className="page-subtitle">
          Check the latest ownership mutation status for a Hyderabad property by assessment number.
        </p>
        <ul className="page-features">
          <li>Live from GHMC</li>
          <li>By the property’s assessment number</li>
          <li>The latest mutation status, as GHMC shows it</li>
        </ul>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <form onSubmit={submit}>
          <div className="field">
            <label>Assessment Number <span className="req">*</span><span className="field-hint">e.g. 1010133899</span></label>
            <input
              type="text"
              inputMode="numeric"
              placeholder="Enter assessment number"
              value={assessmentNumber}
              onChange={(e) => { setAssessmentNumber(e.target.value.replace(/\D/g, '').slice(0, 10)); reset() }}
              disabled={busy}
              autoComplete="off"
            />
          </div>
          {error && <div className="field"><StatusMessage kind="error" message={error} /></div>}
          <button type="submit" className="submit-btn" disabled={busy}>
            <i className="ti ti-home-2" /> Check Mutation Status
          </button>
        </form>
      </div>

      {result && <DocumentResult key={result.filename} first={result} />}

      <LoaderModal visible={busy} onCancel={cancel} title="Checking GHMC…" />
    </div>
  )
}

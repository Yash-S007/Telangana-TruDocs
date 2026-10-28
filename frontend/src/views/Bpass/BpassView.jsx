import { useState } from 'react'
import StatusMessage from '../../components/common/StatusMessage.jsx'
import LoaderModal from '../../components/common/LoaderModal.jsx'
import DocumentResult from '../../components/common/DocumentResult.jsx'
import { bpassDocumentPath, lookupBpass } from '../../utils/api.js'
import { useRequest } from '../../utils/useRequest.js'

// Like the CDMA tool: the official letter in the preview, the application's details, and its other
// letters underneath to switch the preview.
function BpassResult({ result, slot }) {
  const facts = [
    ['Status', result.status], ['Approval for', result.approval_for], ['Type', result.type],
    ['Applied on', result.applied_on], ['Decided on', result.decided_on],
    ['Town', [result.town, result.district].filter(Boolean).join(', ')],
    ['Survey / plot', [result.survey_no && `Survey ${result.survey_no}`, result.plot_no && `Plot ${result.plot_no}`].filter(Boolean).join(' · ')],
    ['Locality', result.locality],
  ].filter(([, v]) => v)
  return (
    <DocumentResult
      slot={slot}
      first={result.doc}
      docs={result.documents.map((d) => ({ key: d.kind, label: d.label, path: bpassDocumentPath(result.file_no, d.kind) }))}
      title={`${result.file_no}${result.town ? ` · ${result.town}` : ''}`}
      facts={facts}
      note="From the old TG-bPASS portal: applications filed before December 2025. Newer ones are on BuildNow."
      loadingText="Getting the letter from the portal…"
      emptyText="Found, but the portal holds no letters for this application."
    />
  )
}

export default function BpassView() {
  const request = useRequest()
  const [slot, setSlot] = useState(null)  // the search card's foot, where the result's line goes
  const { result, busy, error, cancel, fail, reset } = request
  const [fileNo, setFileNo] = useState('')

  function submit(e) {
    e.preventDefault()
    const value = fileNo.trim().toUpperCase()
    if (!/^[A-Z0-9][A-Z0-9/-]{4,39}$/.test(value)) { fail('Please enter the TG-bPASS file number, as on the permission letter.'); return }
    request.run((signal) => lookupBpass(value, { signal }))
  }

  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-badge">
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#1a6b4a', display: 'inline-block' }} />
          TG-bPASS
        </div>
        <h1 className="page-title">Building Permission (TG‑bPASS)</h1>
        <p className="page-subtitle">
          The status of a building permission filed on TG-bPASS before December 2025, and its official letters (permit order, letter of approval to start work), by file number.
        </p>
        <ul className="page-features">
          <li>Status, dates and place of the application</li>
          <li>The official letters, to preview and download</li>
          <li>By the file number on the letter</li>
        </ul>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <div className="field">
          <StatusMessage kind="info" message="Only applications filed on TG-bPASS before December 2025 are available here. Newer ones are on BuildNow." />
        </div>
        <form onSubmit={submit}>
          <div className="field">
            <label>File number <span className="req">*</span><span className="field-hint">On the permission letter or acknowledgement</span></label>
            <input
              type="text"
              placeholder="e.g. 123456/XXXX/0123/2025"
              value={fileNo}
              onChange={(e) => { setFileNo(e.target.value.replace(/\s/g, '')); reset() }}
              disabled={busy}
              autoComplete="off"
              autoCapitalize="characters"
            />
          </div>
          {error && <div className="field"><StatusMessage kind="error" message={error} /></div>}
          <button type="submit" className="submit-btn" disabled={busy}>
            <i className="ti ti-building" /> Show Building Permission
          </button>
        </form>
        <div ref={setSlot} />
      </div>

      {result && <BpassResult key={result.file_no} result={result} slot={slot} />}

      <LoaderModal visible={busy} onCancel={cancel} title="Getting the permission from TG-bPASS…" />
    </div>
  )
}

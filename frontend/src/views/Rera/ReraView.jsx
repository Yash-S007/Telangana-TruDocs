import { useState } from 'react'
import StatusMessage from '../../components/common/StatusMessage.jsx'
import LoaderModal from '../../components/common/LoaderModal.jsx'
import DocumentResult from '../../components/common/DocumentResult.jsx'
import { reraCertificatePath, searchRera } from '../../utils/api.js'
import { useRequest } from '../../utils/useRequest.js'

const CERTIFICATE_LABELS = {
  registration: 'Registration certificate',
  extension: 'Extension certificate',
  'special-extension': '4-month extension',
}

// The projects found, each certificate showing in the preview above when picked (like CDMA's list).
function ReraResults({ result }) {
  const { total, shown, projects } = result
  return (
    <DocumentResult first={null} emptyText="Pick a certificate below to see it here." loadingText="Getting the certificate from TG-RERA…">
      {(button) => (
        <div className="card result-card">
          <StatusMessage kind="success" message={shown < total
            ? `Showing ${shown} of ${total} projects. Add more words to narrow it down.`
            : `${total} project${total === 1 ? '' : 's'} found`} />
          <ul className="doc-list">
            {projects.map((p, i) => (
              <li className="doc-item doc-item-stacked" key={i}>
                <div className="doc-text">
                  <span className="doc-label">{p.project}</span>
                  <span className="doc-meta">{p.promoter} · updated {p.last_modified}</span>
                </div>
                <div className="doc-actions">
                  {p.certificates.map((c) => button({ key: `${i}-${c.kind}`, path: reraCertificatePath(c.kind, c.token), button: CERTIFICATE_LABELS[c.kind] }))}
                  {p.details_url && (
                    <a className="table-action-btn secondary" href={p.details_url} target="_blank" rel="noopener noreferrer">Project details&nbsp;↗</a>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </DocumentResult>
  )
}

export default function ReraView() {
  const request = useRequest()
  const { result, busy, error, cancel, fail, reset } = request
  const [fields, setFields] = useState({ project_name: '', promoter_name: '', registration_no: '' })
  const set = (key) => (e) => { setFields({ ...fields, [key]: e.target.value }); reset() }

  function submit(e) {
    e.preventDefault()
    if (!Object.values(fields).some((v) => v.trim())) {
      fail('Enter a project name, promoter name or registration number.')
      return
    }
    request.run((signal) => searchRera(fields, { signal }))
  }

  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-badge">
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#1a6b4a', display: 'inline-block' }} />
          TG-RERA
        </div>
        <h1 className="page-title">RERA Certificate</h1>
        <p className="page-subtitle">
          The official RERA registration certificate of a real estate project (and its extensions), by project, promoter or registration number.
        </p>
        <ul className="page-features">
          <li>Live from TG-RERA</li>
          <li>Registration and extension certificates as official PDFs</li>
          <li>The project’s official page</li>
        </ul>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <form onSubmit={submit}>
          <div className="field">
            <label>Project name <span className="field-hint">Fill any one box</span></label>
            <input type="text" placeholder="e.g. Avasa Hills" value={fields.project_name} onChange={set('project_name')} maxLength={100} disabled={busy} autoComplete="off" />
          </div>
          <div className="field">
            <label>Promoter / builder name</label>
            <input type="text" placeholder="e.g. YBR Infra" value={fields.promoter_name} onChange={set('promoter_name')} maxLength={50} disabled={busy} autoComplete="off" />
          </div>
          <div className="field">
            <label>RERA registration number</label>
            <input type="text" placeholder="e.g. P02400001224" value={fields.registration_no} onChange={set('registration_no')} maxLength={15} disabled={busy} autoComplete="off" autoCapitalize="characters" />
          </div>
          {error && <div className="field"><StatusMessage kind="error" message={error} /></div>}
          <button type="submit" className="submit-btn" disabled={busy}>
            <i className="ti ti-certificate" /> Find RERA Certificate
          </button>
        </form>
      </div>

      {result && <ReraResults result={result} />}

      <LoaderModal visible={busy} onCancel={cancel} title="Searching TG-RERA…" />
    </div>
  )
}

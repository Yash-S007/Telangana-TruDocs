import { useEffect, useRef, useState } from 'react'
import StatusMessage from './StatusMessage.jsx'
import PDFViewer from './PDFViewer.jsx'
import { getPdf } from '../../utils/api.js'
import { downloadBlob } from '../../utils/pdf.js'

// Like the Karnataka EC tools: "Found! <file>", Download PDF and the PDF preview, then a card with
// the result's details and its other official documents, each of which switches the preview.
//   first:    the document fetched with the result, { key, blob, filename }, or null
//   docs:     [{ key, label, meta?, path?, button?, loadingText? }] (no path = not online)
//   children: (button) => the tool's own lists, where button(doc) shows that document here
export default function DocumentResult({ first, docs = [], title, facts = [], note, loadingText, emptyText, children }) {
  const [doc, setDoc] = useState(first)
  const [loading, setLoading] = useState(null)  // the document being fetched
  const [error, setError] = useState('')
  const generation = useRef(0)
  const controller = useRef(null)

  useEffect(() => {
    const pending = controller
    return () => pending.current?.abort()  // a document still loading when the result goes away
  }, [])

  async function show(item) {
    const gen = ++generation.current
    controller.current?.abort()
    controller.current = new AbortController()
    setLoading(item)
    setError('')
    try {
      const file = await getPdf(item.path, { signal: controller.current.signal })
      if (gen === generation.current) setDoc({ key: item.key, ...file })
    } catch (err) {
      if (gen === generation.current && err.name !== 'AbortError') setError(err.message)
    } finally {
      if (gen === generation.current) setLoading(null)
    }
  }

  const button = (item) => (item.path ? (
    <button type="button" className="table-action-btn" disabled={Boolean(loading) || doc?.key === item.key} onClick={() => show(item)}>
      {loading?.key === item.key ? <><span className="inline-spinner" />Loading…</> : doc?.key === item.key ? 'Showing' : item.button || 'Show'}
    </button>
  ) : (
    <span className="cell-muted">Not online</span>
  ))

  return (
    <>
      <div className="card result-card">
        {loading ? (
          <div className="status-msg info"><span className="inline-spinner" /><span>{loading.loadingText || loadingText}</span></div>
        ) : error ? (
          <StatusMessage kind="error" message={error} />
        ) : doc ? (
          <StatusMessage kind="success" message={`Found! ${doc.filename}`} />
        ) : (
          <StatusMessage kind="info" message={emptyText} />
        )}
        {doc && (
          <div className="result-actions">
            <button type="button" className="download-btn" onClick={() => downloadBlob(doc.blob, doc.filename)}>
              <i className="ti ti-download" /> Download PDF
            </button>
            <span className="result-meta">{doc.filename}</span>
          </div>
        )}
      </div>

      {doc && <PDFViewer blob={doc.blob} filename={doc.filename} />}

      {(title || facts.length > 0 || docs.length > 0 || note) && (
        <div className="card result-card documents">
          {title && <h3 className="result-heading">{title}</h3>}
          {facts.length > 0 && (
            <dl className="record-fields">
              {facts.map(([k, v]) => <div className="record-row" key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
            </dl>
          )}
          {docs.length > 0 && (
            <ul className="doc-list">
              {docs.map((item) => (
                <li className="doc-item" key={item.key}>
                  <div className="doc-text">
                    <span className="doc-label">{item.label}</span>
                    {item.meta && <span className="doc-meta">{item.meta}</span>}
                  </div>
                  {button(item)}
                </li>
              ))}
            </ul>
          )}
          {note && <p className="result-note">{note}</p>}
        </div>
      )}
      {children?.(button)}
    </>
  )
}

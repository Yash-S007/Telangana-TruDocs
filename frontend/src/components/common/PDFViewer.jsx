import { useEffect, useRef } from 'react'
import { downloadBlob, renderPdfToCanvas } from '../../utils/pdf.js'

export default function PDFViewer({ blob, filename }) {
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
        <button
          className="download-btn"
          onClick={() => downloadBlob(blob, filename || 'EC.pdf')}
          style={{ padding: '6px 12px', fontSize: 13 }}
        >
          <i className="ti ti-download" /> Download
        </button>
      </div>
      <div ref={containerRef} className="pdf-canvas-container" />
    </div>
  )
}

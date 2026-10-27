// The PDF helpers of trudocs-state's frontend shell (frontend-shell/src/utils/pdf.js), except that
// pdf.js is loaded the first time a PDF is shown, so pages without one don't download it.
let pdfjsLib

async function loadPdfjs() {
  if (!pdfjsLib) {
    const [lib, worker] = await Promise.all([import('pdfjs-dist'), import('pdfjs-dist/build/pdf.worker.mjs?url')])
    lib.GlobalWorkerOptions.workerSrc = worker.default
    pdfjsLib = lib
  }
  return pdfjsLib
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  setTimeout(() => {
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }, 100)
}

// Every page is a canvas held in memory, so the preview draws at most 10 pages, at no more than 2×
// (a phone shows a page under 1,100 pixels wide): a 25-page scanned 22-A list at an iPhone's 3×
// would take ~450 MB, more than Safari allows. Download PDF always has every page.
const MAX_PAGES = 10

// `isCancelled` lets the caller abandon a stale render (effect cleanup / newer blob).
// Without it, two overlapping renders into one container both append their pages.
export async function renderPdfToCanvas(blob, container, isCancelled = () => false) {
  try {
    const lib = await loadPdfjs()
    const arrayBuffer = await blob.arrayBuffer()
    const pdf = await lib.getDocument({ data: arrayBuffer }).promise
    if (isCancelled()) return
    container.innerHTML = ''

    for (let pageNum = 1; pageNum <= Math.min(pdf.numPages, MAX_PAGES); pageNum++) {
      const page = await pdf.getPage(pageNum)
      if (isCancelled()) return
      const viewport = page.getViewport({ scale: Math.min(window.devicePixelRatio || 1.5, 2) })
      const canvas = document.createElement('canvas')
      const ctx = canvas.getContext('2d')
      canvas.width = viewport.width
      canvas.height = viewport.height
      canvas.style.width = '100%'
      canvas.style.display = 'block'
      canvas.style.borderRadius = '4px'
      container.appendChild(canvas)
      await page.render({ canvasContext: ctx, viewport }).promise
    }
    if (pdf.numPages > MAX_PAGES && !isCancelled()) {
      const more = document.createElement('p')
      more.className = 'pdf-more-pages'
      more.textContent = `Showing the first ${MAX_PAGES} of ${pdf.numPages} pages. Download the PDF to see them all.`
      container.appendChild(more)
    }
  } catch {
    container.innerHTML = '<p style="padding:16px;color:#f87171">Could not render PDF preview.</p>'
  }
}

const SEARCH_TIMEOUT_MS = 150_000

async function fetchWithTimeout(url, options = {}) {
  const { signal: userSignal, ...restOptions } = options
  const controller = new AbortController()
  const id = setTimeout(() => controller.abort(), SEARCH_TIMEOUT_MS)
  // Forward the caller's abort signal so cancelSearch() actually stops the fetch
  if (userSignal) {
    if (userSignal.aborted) { clearTimeout(id); throw new DOMException('Aborted', 'AbortError') }
    userSignal.addEventListener('abort', () => controller.abort(), { once: true })
  }
  try {
    const res = await fetch(url, { ...restOptions, signal: controller.signal })
    return res
  } finally {
    clearTimeout(id)
  }
}

// ── Error normalization ──────────────────────────────────────────────────────
// Map any backend error to a friendly, user-facing message. NEVER expose raw HTTP
// status codes or internal jargon. Keep the genuinely useful messages (no-records,
// rate-limit); everything else collapses to one clean line.
function friendlyMessage(status, detail) {
  if (status === 404) return detail || 'No records found for your search.'
  if (status === 429) return detail || 'Too many searches right now. Please wait a minute and try again.'
  if (status >= 500) return 'The records service is temporarily busy. Please try again shortly.'
  if (status === 401 || status === 403) return 'Please try again in a moment.'
  return 'Something went wrong. Please try again.'
}

// Build (don't throw) a friendly Error. `code` carries the status for callers that
// branch on it; `detail` keeps raw backend text for logging only (never rendered).
function makeFriendlyError(status, detail = '') {
  const err = new Error(friendlyMessage(status, detail))
  err.code = status
  err.detail = detail
  return err
}

// Read the response body (best-effort) and throw a friendly Error. Use at every
// terminal non-2xx site where the body hasn't already been consumed.
async function throwFriendly(res) {
  let detail = ''
  try {
    const d = await res.json()
    detail = d?.detail || d?.message || d?.error || ''
    if (Array.isArray(detail)) detail = detail.map((e) => e?.msg || '').join('; ')
  } catch { /* non-JSON body */ }
  throw makeFriendlyError(res.status, detail)
}

// ── Telangana tools ──────────────────────────────────────────────────────────
// Our backend's messages are already written for the user (portal down or slow, nothing found,
// check your input), so, like the BBMP tools', they're shown as they come. A request that never
// reached us, or ran past the time limit, gets its own plain sentence (never "Failed to fetch").

async function throwTelangana(res) {
  let detail = ''
  try { detail = (await res.json())?.detail } catch { /* not JSON: an HTML error page */ }
  const err = new Error(typeof detail === 'string' && detail ? detail
    : res.status === 429 ? 'Too many searches right now. Please wait a minute and try again.'
    : res.status >= 500 ? "The government portal isn't responding right now. Please try again in a few minutes."
    : 'Please check the details you entered and try again.')
  err.code = res.status
  throw err
}

async function send(path, options = {}) {
  let res
  try {
    res = await fetchWithTimeout(path, options)
  } catch (err) {
    if (err.name === 'AbortError') {
      if (options.signal?.aborted) throw err  // the user cancelled
      throw new Error('The government portal is taking too long to respond. Please try again shortly.')
    }
    throw new Error("Can't reach TruDocs right now. Please check your internet connection and try again.")
  }
  if (!res.ok) await throwTelangana(res)
  return res
}

const getJson = (path, { signal } = {}) => send(path, { signal }).then((r) => r.json().catch(() => ({})))

const post = (path, body, signal) => send(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
  signal,
})

const postJson = (path, body, { signal } = {}) => post(path, body, signal).then((r) => r.json().catch(() => ({})))

// A PDF for the preview (an official one, or ours of a result): its bytes and the server's file name.
async function asPdf(res) {
  const m = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') || '')
  return { blob: await res.blob(), filename: m ? m[1] : 'document.pdf' }
}

export const getPdf = (path, { signal } = {}) => send(path, { signal }).then(asPdf)

// POST, so what was searched (a passbook number, an owner's PTIN) stays out of the access log.
const postPdf = (path, body, { signal } = {}) => post(path, body, signal).then(asPdf)

// A result with its first PDF, for the preview. If only the PDF fails (a portal that can't send
// it, a slow photo), the result still shows, with the reason where the PDF would be.
async function withPreview(result, key, fetchPdf) {
  try {
    return { ...result, doc: { key, ...(await fetchPdf()) }, docError: '' }
  } catch (err) {
    if (err.name === 'AbortError') throw err
    return { ...result, doc: null, docError: err.message }
  }
}

// ── Village search (a pre-scraped list per portal, searched on our server) ───

export const searchVillages = (portal, q, opts) =>
  getJson(`/api/${portal}/villages/search?${new URLSearchParams({ q })}`, opts)

// ── Market Value (IGRS) ──────────────────────────────────────────────────────

// The rates as our PDF (the page shows only the PDF).
export const marketValuePdf = (body, opts) => postPdf('/api/market-value/pdf', body, opts)

export const loadHyderabadDivisions = (opts) => getJson('/api/market-value/hyderabad/divisions', opts)

export const searchHyderabadLocalities = (divisionId, q, opts) =>
  getJson(`/api/market-value/hyderabad/localities?${new URLSearchParams({ division_id: divisionId, q })}`, opts)

// ── Land Details (Bhu Bharati) ───────────────────────────────────────────────

export const loadLandSurveys = (villageId, opts) =>
  getJson(`/api/pattadar/survey-options/${encodeURIComponent(villageId)}`, opts)

export const loadLandKhatas = (villageId, surveyNo, opts) =>
  getJson(`/api/pattadar/khata-options/${encodeURIComponent(villageId)}?${new URLSearchParams({ survey_no: surveyNo })}`, opts)

// The record as our PDF (the page shows only the PDF).
export const landSurveyPdf = (body, opts) => postPdf('/api/pattadar/pdf', body, opts)

export const landPassbookPdf = (body, opts) => postPdf('/api/pattadar/pdf-by-passbook', body, opts)

// ── Adangal (Pahani) ─────────────────────────────────────────────────────────

export const loadAdangalSurveys = (villageId, opts) =>
  getJson(`/api/adangal/survey-options/${encodeURIComponent(villageId)}`, opts)

// The Pahani as our PDF (the page shows only the PDF).
export const adangalPdf = (body, opts) => postPdf('/api/adangal/pdf', body, opts)

// ── Prohibited Lands (IGRS Section 22A) ──────────────────────────────────────

export const loadProhibitedSros = (divisionId, opts) =>
  getJson(`/api/prohibited-lands/hyderabad/sros?${new URLSearchParams({ division_id: divisionId })}`, opts)

export const loadProhibitedSurveyList = (location, kind, opts) =>
  postJson('/api/prohibited-lands/survey-list', { ...location, kind }, opts)

export const prohibitedPdfPath = (location, kind, formtype) =>
  `/api/prohibited-lands/pdf?${new URLSearchParams({ ...location, kind, formtype })}`

export const prohibitedOrderPath = (orderId, flag) =>
  `/api/prohibited-lands/order?${new URLSearchParams({ order_id: orderId, flag })}`

// The place's 22-A lists and the first one that's online, so the result opens with its preview.
export async function lookupProhibited(location, opts) {
  const data = await postJson('/api/prohibited-lands/categories', location, opts)
  const kind = Object.keys(data.categories || {}).find((k) => data.categories[k].some((c) => c.available))
  const first = kind && data.categories[kind].find((c) => c.available)
  if (!first) return { ...data, doc: null }
  return withPreview(data, `${kind}-${first.formtype}`, () => getPdf(prohibitedPdfPath(location, kind, first.formtype), opts))
}

// ── Survey Map and Village Map (TGRAC village maps) ──────────────────────────

export const loadSurveyMapSurveys = (dmv, opts) =>
  getJson(`/api/survey-map/survey-options/${encodeURIComponent(dmv)}`, opts)

// A survey number and its map as our PDF together, so the result opens with its preview.
export async function lookupSurveyMap(dmv, surveyNo, opts) {
  const body = { dmv, survey_no: surveyNo }
  const parcel = await postJson('/api/survey-map/parcel', body, opts)
  return withPreview(parcel, 'map', () => postPdf('/api/survey-map/pdf', body, opts))
}

// A village's map and its A3 PDF together, so the result opens with its preview.
export async function lookupVillageMap(dmv, opts) {
  const map = await getJson(`/api/village-map/map/${encodeURIComponent(dmv)}`, opts)
  return withPreview(map, 'map', () => getPdf(`/api/village-map/pdf/${encodeURIComponent(dmv)}`, opts))
}

// ── Hydra FTL Map (HMDA lakes) ───────────────────────────────────────────────

export const loadLakePlaces = (opts) => getJson('/api/hydra-ftl/places', opts)

export const findLakes = (params, opts) => getJson(`/api/hydra-ftl/lakes?${new URLSearchParams(params)}`, opts)

export const lakeDocumentPath = (key, kind) => `/api/hydra-ftl/document?${new URLSearchParams({ key, kind })}`

// A lake and its FTL map together, so the result opens with its preview.
export async function lookupLake(key, opts) {
  const lake = await getJson(`/api/hydra-ftl/lake?${new URLSearchParams({ key })}`, opts)
  const first = lake.documents?.[0]
  return { ...lake, doc: first ? { key: first.kind, ...(await getPdf(lakeDocumentPath(lake.key, first.kind), opts)) } : null }
}

// ── GHMC (Hyderabad) ─────────────────────────────────────────────────────────

// The records as our PDFs (the pages show only the PDF).
export const ghmcMutationPdf = (assessmentNumber, opts) =>
  postPdf('/api/ghmc/mutation/pdf', { assessment_number: assessmentNumber }, opts)

export const loadGhmcCircles = (opts) => getJson('/api/ghmc/circles', opts)

export const ghmcPropertyTaxPdf = (circle, ptin, opts) => postPdf('/api/ghmc/property-tax/pdf', { circle, ptin }, opts)

// ── CDMA Property Tax Receipt (towns outside Hyderabad) ──────────────────────

export const loadCdmaTowns = (opts) => getJson('/api/cdma-tax/towns', opts)

export const findCdmaProperties = (body, opts) => postJson('/api/cdma-tax/find', body, opts)

export const cdmaDetailsPath = (ptin) => `/api/cdma-tax/pdf/${encodeURIComponent(ptin)}`

export const cdmaReceiptPath = (ptin, receipt) =>
  `/api/cdma-tax/receipt?${new URLSearchParams({ ptin, receipt_no: receipt.receipt_no, slno: receipt.slno })}`

// A property and its details PDF together, so the result opens with its preview.
export async function lookupCdmaProperty(ptin, opts) {
  const data = await postJson('/api/cdma-tax/property', { ptin }, opts)
  return { ...data, doc: { key: 'details', ...(await getPdf(cdmaDetailsPath(ptin), opts)) } }
}

// ── TG-bPASS Building Permission ─────────────────────────────────────────────

export const bpassDocumentPath = (fileNo, kind) => `/api/bpass/document?${new URLSearchParams({ file_no: fileNo, kind })}`

// An application and its main letter together, so the result opens with its preview.
export async function lookupBpass(fileNo, opts) {
  const data = await postJson('/api/bpass/application', { file_no: fileNo }, opts)
  const first = data.documents?.[0]
  return { ...data, doc: first ? { key: first.kind, ...(await getPdf(bpassDocumentPath(data.file_no, first.kind), opts)) } : null }
}

// ── RERA Certificate (TG-RERA) ───────────────────────────────────────────────

export const searchRera = (fields, opts) => postJson('/api/rera/search', fields, opts)

export const reraCertificatePath = (kind, token) => `/api/rera/certificate?${new URLSearchParams({ kind, token })}`

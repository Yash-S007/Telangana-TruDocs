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

const postJson = (path, body, { signal } = {}) => send(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
  signal,
}).then((r) => r.json().catch(() => ({})))

// ── Village search (a pre-scraped list per portal, searched on our server) ───

export const searchVillages = (portal, q, opts) =>
  getJson(`/api/${portal}/villages/search?${new URLSearchParams({ q })}`, opts)

// ── Market Value (IGRS) ──────────────────────────────────────────────────────

export const searchMarketValue = (body, opts) => postJson('/api/market-value/search', body, opts)

export const loadHyderabadDivisions = (opts) => getJson('/api/market-value/hyderabad/divisions', opts)

export const searchHyderabadLocalities = (divisionId, q, opts) =>
  getJson(`/api/market-value/hyderabad/localities?${new URLSearchParams({ division_id: divisionId, q })}`, opts)

// ── Land Details (Bhu Bharati) ───────────────────────────────────────────────

export const loadLandSurveys = (villageId, opts) =>
  getJson(`/api/pattadar/survey-options/${encodeURIComponent(villageId)}`, opts)

export const loadLandKhatas = (villageId, surveyNo, opts) =>
  getJson(`/api/pattadar/khata-options/${encodeURIComponent(villageId)}?${new URLSearchParams({ survey_no: surveyNo })}`, opts)

export const searchLandBySurvey = (body, opts) => postJson('/api/pattadar/search', body, opts)

export const searchLandByPassbook = (body, opts) => postJson('/api/pattadar/search-by-passbook', body, opts)


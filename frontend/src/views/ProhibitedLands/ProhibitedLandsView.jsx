import { useEffect, useState } from 'react'
import VillageSearch from '../../components/common/VillageSearch.jsx'
import SelectLoading from '../../components/common/SelectLoading.jsx'
import StatusMessage from '../../components/common/StatusMessage.jsx'
import LoaderModal from '../../components/common/LoaderModal.jsx'
import DocumentResult from '../../components/common/DocumentResult.jsx'
import {
  loadProhibitedSros, loadProhibitedSurveyList, lookupProhibited, prohibitedOrderPath, prohibitedPdfPath,
} from '../../utils/api.js'
import { useRequest } from '../../utils/useRequest.js'

const KIND_LABELS = { AGRI: 'Agriculture', NONAGRI: 'Non-Agriculture' }
const SURVEY_ROWS_SHOWN = 200

// "166" + "3" → "166/3". The portal writes "-" or "" for an empty part.
const joinNo = (a, b) => [a, b].filter((x) => x && x !== '-').join('/') || '-'

// One row per 22-A(1) category, one column per land kind, each showing the official PDF above.
function Categories({ location, place, categories, button }) {
  const kinds = Object.keys(categories)
  const labels = categories[kinds[0]].map((c) => c.label)
  return (
    <div className="card result-card">
      <h3 className="result-heading">Section 22-A lists for {place}</h3>
      <div className="result-table-wrapper">
        <table className="result-table result-table-compact stack-on-mobile">
          <thead>
            <tr>
              <th>Section 22-A(1)</th>
              {kinds.map((k) => <th key={k}>{KIND_LABELS[k]}</th>)}
            </tr>
          </thead>
          <tbody>
            {labels.map((label) => (
              <tr key={label}>
                <td data-label="Section 22-A(1)">{label}</td>
                {kinds.map((k) => {
                  const c = categories[k].find((x) => x.label === label)
                  return (
                    <td key={k} data-label={KIND_LABELS[k]}>
                      {button({ key: `${k}-${c?.formtype}`, path: c?.available ? prohibitedPdfPath(location, k, c.formtype) : null, button: 'Show PDF' })}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {kinds.some((k) => categories[k].some((c) => !c.available)) && (
        <p className="result-note">"Not online": the department doesn't publish these lists on its website.</p>
      )}
    </div>
  )
}

// The survey-wise list behind "Court cases & Others". Like the official page, it loads every row
// once and filters in the browser; big areas can take a while. Each order shows in the preview.
function SurveyList({ location, kind, button }) {
  const [state, setState] = useState({ data: null, error: '' })
  const [filter, setFilter] = useState('')

  useEffect(() => {
    const ctrl = new AbortController()
    loadProhibitedSurveyList(location, kind, { signal: ctrl.signal })
      .then((data) => setState({ data, error: '' }))
      .catch((err) => { if (err.name !== 'AbortError') setState({ data: null, error: err.message }) })
    return () => ctrl.abort()
  }, [location, kind])

  const { data, error } = state
  const q = filter.trim().toUpperCase()
  const matches = !data ? [] : !q ? data.rows : data.rows.filter((r) => [
    joinNo(r.survey_no, r.sub_survey_no), joinNo(r.rev_survey_no, r.rev_sub_survey_no),
    r.door_no, r.ward_block, r.plot_no, r.reason, r.order_no, r.order_date, r.sro,
  ].some((v) => v && v.toUpperCase().includes(q)))
  const shown = matches.slice(0, SURVEY_ROWS_SHOWN)

  return (
    <div className="card result-card survey-list">
      <h3 className="result-heading">Survey list: {KIND_LABELS[kind]}{data && ` (${data.count})`}</h3>
      {error ? (
        <StatusMessage kind="error" message={`${error} Press "Check Prohibited Lands" to try again.`} />
      ) : !data ? (
        <p className="result-loading"><span className="inline-spinner" />Loading the survey list… large areas like Hyderabad can take up to a minute.</p>
      ) : data.count === 0 ? (
        <p className="result-note">No prohibited properties are listed here.</p>
      ) : (
        <>
          <input
            type="text"
            className="result-filter"
            placeholder="Search survey no., door no., plot no., reason…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <p className="result-note">
            {q ? `${matches.length} of ${data.count} match` : `${data.count} listed`}
            {matches.length > SURVEY_ROWS_SHOWN ? `, showing the first ${SURVEY_ROWS_SHOWN}. Type to narrow down.` : ''}
          </p>
          <div className="result-table-wrapper">
            <table className="result-table stack-on-mobile">
              <thead>
                <tr>
                  <th>Survey No.</th>
                  <th>Rev. Survey No.</th>
                  <th>Door No.</th>
                  <th>Ward-Block</th>
                  <th>Plot No.</th>
                  <th>Extent (Unit)</th>
                  <th>Reason</th>
                  <th>Order / Notification</th>
                  <th>Volume / Page</th>
                  <th>SRO</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r, i) => (
                  <tr key={i}>
                    <td data-label="Survey No.">{joinNo(r.survey_no, r.sub_survey_no)}</td>
                    <td data-label="Rev. Survey No.">{joinNo(r.rev_survey_no, r.rev_sub_survey_no)}</td>
                    <td data-label="Door No.">{r.door_no}</td>
                    <td data-label="Ward-Block">{r.ward_block}</td>
                    <td data-label="Plot No.">{r.plot_no}</td>
                    <td data-label="Extent">{r.extent}</td>
                    <td data-label="Reason">{r.reason}</td>
                    <td data-label="Order">
                      <span>
                        {r.order_no}
                        {r.order_date && <><br />{r.order_date}</>}
                        {r.order_id && <><br />{button({ key: `order-${r.order_id}`, path: prohibitedOrderPath(r.order_id, r.order_flag), button: 'Show order' })}</>}
                      </span>
                    </td>
                    <td data-label="Volume / Page">{r.volume_page}</td>
                    <td data-label="SRO">{r.sro}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

export default function ProhibitedLandsView() {
  const request = useRequest()
  const { result, busy, error, cancel, fail, reset } = request
  const [village, setVillage] = useState(null)
  const [sros, setSros] = useState({ loading: false, list: [] })
  const [sroCode, setSroCode] = useState('')
  const isHyderabad = village?.district_id === '16_1'

  async function onVillage(v) {
    setVillage(v)
    setSros({ loading: v?.district_id === '16_1', list: [] })
    setSroCode('')
    reset()
    // Hyderabad's entries are divisions, and the portal needs one SRO office picked.
    if (v?.district_id !== '16_1') return
    try {
      setSros({ loading: false, list: await loadProhibitedSros(v.village_id) })
    } catch (err) {
      setSros({ loading: false, list: [] })
      fail(err.message)
    }
  }

  function submit(e) {
    e.preventDefault()
    if (!village) { fail('Please select a village first.'); return }
    if (isHyderabad && !sroCode) { fail('Please select the SRO office.'); return }
    const location = {
      district_id: village.district_id,
      mandal_id: village.mandal_id,
      village_id: village.village_id,
      sro_code: isHyderabad ? sroCode : '',
    }
    const place = `${village.village}, ${village.mandal}`
    request.run(async (signal) => ({ location, place, ...(await lookupProhibited(location, { signal })) }))
  }

  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-badge">
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#1a6b4a', display: 'inline-block' }} />
          Registration dept
        </div>
        <h1 className="page-title">Prohibited Lands (Section 22A)</h1>
        <p className="page-subtitle">
          Official lists of properties barred from registration under Section 22-A, for agricultural and non-agricultural land by village, with the government orders behind each entry.
        </p>
        <ul className="page-features">
          <li>Live from IGRS, the Registration department</li>
          <li>The official PDF for each 22-A(1) category</li>
          <li>The survey-wise list, searchable, with each order</li>
        </ul>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <form onSubmit={submit}>
          <div className="field">
            <label>Village / Mandal <span className="req">*</span><span className="field-hint">Hyderabad: type the division, e.g. Secunderabad</span></label>
            <VillageSearch portal="prohibited-lands" onSelect={onVillage} disabled={busy} />
          </div>
          {isHyderabad && (
            <div className="field">
              <label>SRO Office <span className="req">*</span></label>
              <SelectLoading loading={sros.loading} value={sroCode} onChange={(e) => { setSroCode(e.target.value); reset() }} disabled={busy}>
                <option value="">{sros.loading ? 'Loading SRO offices…' : 'Select SRO office'}</option>
                {sros.list.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </SelectLoading>
            </div>
          )}
          {error && <div className="field"><StatusMessage kind="error" message={error} /></div>}
          <button type="submit" className="submit-btn" disabled={busy || !village || (isHyderabad && !sroCode)}>
            <i className="ti ti-ban" /> Check Prohibited Lands
          </button>
        </form>
      </div>

      {result?.categories && (
        <DocumentResult key={new URLSearchParams(result.location).toString()} first={result.doc} firstError={result.docError}
          loadingText="Getting the official PDF from IGRS…" emptyText="None of the 22-A lists for this place is online.">
          {(button) => (
            <>
              <Categories location={result.location} place={result.place} categories={result.categories} button={button} />
              {Object.keys(result.categories).map((k) => <SurveyList key={k} location={result.location} kind={k} button={button} />)}
            </>
          )}
        </DocumentResult>
      )}

      <LoaderModal visible={busy} onCancel={cancel} title="Checking IGRS for prohibited lands…" />
    </div>
  )
}

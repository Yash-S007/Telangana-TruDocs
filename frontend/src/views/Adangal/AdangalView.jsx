import { useRef, useState } from 'react'
import VillageSearch from '../../components/common/VillageSearch.jsx'
import SelectLoading from '../../components/common/SelectLoading.jsx'
import StatusMessage from '../../components/common/StatusMessage.jsx'
import LoaderModal from '../../components/common/LoaderModal.jsx'
import DocumentResult from '../../components/common/DocumentResult.jsx'
import { adangalPdf, loadAdangalSurveys } from '../../utils/api.js'
import { useRequest } from '../../utils/useRequest.js'

export default function AdangalView() {
  const request = useRequest()
  const { result, busy, error, cancel, fail, reset } = request
  const [village, setVillage] = useState(null)
  const [surveys, setSurveys] = useState({ loading: false, list: [] })
  const [surveyNo, setSurveyNo] = useState('')
  const latest = useRef(0)  // a survey list for a village the user has since changed must not land

  async function onVillage(v) {
    const mine = ++latest.current
    setVillage(v)
    setSurveys({ loading: Boolean(v), list: [] })
    setSurveyNo('')
    reset()
    if (!v) return
    try {
      const list = await loadAdangalSurveys(v.village_id)
      if (latest.current === mine) setSurveys({ loading: false, list })
    } catch {
      // the portal often has no list for a village: the number can still be typed in
      if (latest.current === mine) setSurveys({ loading: false, list: [] })
    }
  }

  function submit(e) {
    e.preventDefault()
    if (!village) { fail('Please select a village first.'); return }
    if (!surveyNo.trim()) { fail('Please enter the survey number.'); return }
    request.run((signal) => adangalPdf({
      district_id: village.district_id,
      division_id: village.division_id,
      mandal_id: village.mandal_id,
      village_id: village.village_id,
      survey_or_khata_value: surveyNo.trim(),
      option: 'surveyNo',
    }, { signal }))
  }

  const manual = village && !surveys.loading && surveys.list.length === 0
  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-badge">
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#1a6b4a', display: 'inline-block' }} />
          Revenue dept
        </div>
        <h1 className="page-title">Adangal Extract (Pahani)</h1>
        <p className="page-subtitle">
          Land ownership, cultivation, and usage record for agricultural land by village and survey number.
        </p>
        <ul className="page-features">
          <li>Live from the Revenue department’s Adangal records</li>
          <li>Pick the survey number, or type it in</li>
          <li>The record as the portal shows it</li>
        </ul>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <form onSubmit={submit}>
          <div className="field">
            <label>Village / Division <span className="req">*</span></label>
            <VillageSearch portal="adangal" onSelect={onVillage} disabled={busy} />
          </div>
          <div className="field">
            <label>Survey Number <span className="req">*</span>{manual && <span className="field-hint">Enter manually</span>}</label>
            {manual || !village ? (
              <input
                type="text"
                placeholder={village ? 'e.g. 123 or 5A' : 'Select village first'}
                value={surveyNo}
                onChange={(e) => { setSurveyNo(e.target.value); reset() }}
                disabled={!village || busy}
                autoComplete="off"
              />
            ) : (
              <SelectLoading loading={surveys.loading} value={surveyNo} onChange={(e) => { setSurveyNo(e.target.value); reset() }} disabled={busy}>
                <option value="">{surveys.loading ? 'Loading surveys…' : 'Select survey number'}</option>
                {surveys.list.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </SelectLoading>
            )}
          </div>
          {error && <div className="field"><StatusMessage kind="error" message={error} /></div>}
          <button type="submit" className="submit-btn" disabled={busy || !village}>
            <i className="ti ti-notebook" /> Get Adangal
          </button>
        </form>
      </div>

      {result && <DocumentResult key={result.filename} first={result} />}

      <LoaderModal visible={busy} onCancel={cancel} title="Fetching the Adangal from the Revenue portal…" />
    </div>
  )
}

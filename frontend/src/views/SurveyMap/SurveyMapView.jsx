import { useRef, useState } from 'react'
import VillageSearch from '../../components/common/VillageSearch.jsx'
import SelectLoading from '../../components/common/SelectLoading.jsx'
import StatusMessage from '../../components/common/StatusMessage.jsx'
import LoaderModal from '../../components/common/LoaderModal.jsx'
import DocumentResult from '../../components/common/DocumentResult.jsx'
import { loadSurveyMapSurveys, lookupSurveyMap } from '../../utils/api.js'
import { useRequest } from '../../utils/useRequest.js'

// Everything the page showed is in the PDF; the page adds what a PDF can't: the spot in Google Maps.
function SurveyMapResult({ result }) {
  const { lat, lon } = result.centre
  return (
    <DocumentResult first={result.doc}>
      {() => (
        <div className="card result-card">
          <h3 className="result-heading">Survey No. {result.survey_no} · {result.village}, {result.mandal}, {result.district}</h3>
          <a className="maps-link" href={`https://www.google.com/maps/search/?api=1&query=${lat},${lon}`} target="_blank" rel="noopener noreferrer">
            <i className="ti ti-map-pin" /> Open in Google Maps
          </a>
        </div>
      )}
    </DocumentResult>
  )
}

export default function SurveyMapView() {
  const request = useRequest()
  const { result, busy, error, cancel, fail, reset } = request
  const [village, setVillage] = useState(null)
  const [surveys, setSurveys] = useState({ loading: false, list: [] })
  const [surveyNo, setSurveyNo] = useState('')
  // A village's first survey list takes 15-25s, so a list for a village the user has since
  // changed must not land under the new one.
  const picked = useRef(null)

  async function onVillage(v) {
    picked.current = v
    setVillage(v)
    setSurveys({ loading: Boolean(v), list: [] })
    setSurveyNo('')
    reset()
    if (!v) return
    try {
      const list = await loadSurveyMapSurveys(v.dmv)
      if (picked.current === v) setSurveys({ loading: false, list })
    } catch (err) {
      if (picked.current === v) { setSurveys({ loading: false, list: [] }); fail(err.message) }
    }
  }

  function submit(e) {
    e.preventDefault()
    if (!village) { fail('Please select a village first.'); return }
    if (!surveyNo) { fail('Please choose the survey number.'); return }
    request.run((signal) => lookupSurveyMap(village.dmv, surveyNo, { signal }))
  }

  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-badge">
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#1a6b4a', display: 'inline-block' }} />
          Land survey
        </div>
        <h1 className="page-title">Survey Map</h1>
        <p className="page-subtitle">
          A survey number’s boundary on a satellite map, with its corner GPS points and area, by village and survey number.
        </p>
        <ul className="page-features">
          <li>Government village maps from TGRAC</li>
          <li>Corner GPS points and the area in acres and guntas</li>
          <li>Open the spot in Google Maps</li>
        </ul>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <form onSubmit={submit}>
          <div className="field">
            <label>Village / Mandal <span className="req">*</span></label>
            <VillageSearch portal="survey-map" onSelect={onVillage} disabled={busy} />
          </div>
          <div className="field">
            <label>Survey Number <span className="req">*</span>{surveys.loading && <span className="field-hint">A village’s first look-up can take up to a minute</span>}</label>
            <SelectLoading loading={surveys.loading} value={surveyNo} onChange={(e) => { setSurveyNo(e.target.value); reset() }} disabled={!village || busy}>
              <option value="">{surveys.loading ? 'Loading survey numbers…' : village ? 'Select survey number' : 'Select village first'}</option>
              {surveys.list.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </SelectLoading>
          </div>
          {error && <div className="field"><StatusMessage kind="error" message={error} /></div>}
          <button type="submit" className="submit-btn" disabled={busy || !village || !surveyNo}>
            <i className="ti ti-map-search" /> Show Survey Map
          </button>
        </form>
      </div>

      {result && <SurveyMapResult key={`${result.village}-${result.survey_no}`} result={result} />}

      <LoaderModal visible={busy} onCancel={cancel} title="Drawing the survey map…" />
    </div>
  )
}

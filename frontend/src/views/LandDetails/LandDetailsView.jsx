import { useEffect, useEffectEvent, useRef, useState } from 'react'
import VillageSearch from '../../components/common/VillageSearch.jsx'
import SelectLoading from '../../components/common/SelectLoading.jsx'
import StatusMessage from '../../components/common/StatusMessage.jsx'
import LoaderModal from '../../components/common/LoaderModal.jsx'
import DocumentResult from '../../components/common/DocumentResult.jsx'
import { landPassbookPdf, landSurveyPdf, loadLandKhatas, loadLandSurveys } from '../../utils/api.js'
import { useRequest } from '../../utils/useRequest.js'

// The portal's two public search modes. Each is its own sub-form, so switching mode remounts it
// and clears the other's state.
const MODES = [
  { value: 'survey', label: 'Survey / Khata number' },
  { value: 'passbook', label: 'Passbook + Aadhaar' },
]

function SurveyFields({ request }) {
  const [village, setVillage] = useState(null)
  const [surveys, setSurveys] = useState({ loading: false, list: [] })
  const [khatas, setKhatas] = useState({ loading: false, list: [] })
  const [surveyNo, setSurveyNo] = useState('')
  const [khataId, setKhataId] = useState('')
  // A list for a village or survey number the user has since changed must not land.
  const latest = useRef(0)
  const { fail, reset, busy } = request

  async function onVillage(v) {
    const mine = ++latest.current
    setVillage(v)
    setSurveys({ loading: Boolean(v), list: [] })
    setKhatas({ loading: false, list: [] })
    setSurveyNo(''); setKhataId('')
    reset()
    if (!v) return
    try {
      const list = await loadLandSurveys(v.village_id)
      if (latest.current === mine) setSurveys({ loading: false, list })
    } catch (err) {
      if (latest.current === mine) { setSurveys({ loading: false, list: [] }); fail(err.message) }
    }
  }

  async function onSurvey(value, typed = false) {
    const mine = ++latest.current
    if (!typed) setSurveyNo(value)
    setKhatas({ loading: Boolean(value), list: [] })
    setKhataId('')
    reset()
    if (!value) return
    try {
      const list = await loadLandKhatas(village.village_id, value)
      if (latest.current === mine) {
        setKhatas({ loading: false, list })
        if (!list.length) fail('No khata numbers found for this survey number. Please check the number.')
      }
    } catch (err) {
      if (latest.current === mine) { setKhatas({ loading: false, list: [] }); fail(err.message) }
    }
  }

  function submit(e) {
    e.preventDefault()
    if (!village) { fail('Please select a village first.'); return }
    if (!surveyNo.trim()) { fail('Please choose the survey number.'); return }
    if (!khataId) { fail('Please choose the khata number.'); return }
    request.run((signal) => landSurveyPdf({
      district_id: village.district_id,
      mandal_id: village.mandal_id,
      village_id: village.village_id,
      survey_no: surveyNo,
      khata_id: khataId,
    }, { signal }))
  }

  const manual = village && !surveys.loading && surveys.list.length === 0
  // A typed survey number (the portal gave no list) loads its khata numbers once typing pauses.
  const loadTyped = useEffectEvent((value) => onSurvey(value, true))
  useEffect(() => {
    if (!manual || !surveyNo.trim()) return
    const t = setTimeout(() => loadTyped(surveyNo.trim()), 600)
    return () => clearTimeout(t)
  }, [manual, surveyNo])

  return (
    <form onSubmit={submit}>
      <div className="field">
        <label>Village / Mandal <span className="req">*</span></label>
        <VillageSearch portal="pattadar" onSelect={onVillage} disabled={busy} />
      </div>
      <div className="field">
        <label>Survey No. / Sub-Division No. <span className="req">*</span>{manual && <span className="field-hint">Enter manually</span>}</label>
        {manual ? (
          <input
            type="text"
            placeholder="e.g. 123 or 1/2A"
            value={surveyNo}
            onChange={(e) => { ++latest.current; setSurveyNo(e.target.value); setKhatas({ loading: false, list: [] }); setKhataId(''); reset() }}
            disabled={busy}
            autoComplete="off"
          />
        ) : (
          <SelectLoading loading={surveys.loading} value={surveyNo} onChange={(e) => onSurvey(e.target.value)} disabled={!village || busy}>
            <option value="">{surveys.loading ? 'Loading surveys…' : village ? 'Select survey number' : 'Select village first'}</option>
            {surveys.list.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
          </SelectLoading>
        )}
      </div>
      <div className="field">
        <label>Khata Number <span className="req">*</span></label>
        <SelectLoading loading={khatas.loading} value={khataId} onChange={(e) => { setKhataId(e.target.value); reset() }} disabled={!surveyNo || busy}>
          <option value="">{khatas.loading ? 'Loading khata numbers…' : 'Select khata number'}</option>
          {khatas.list.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
        </SelectLoading>
      </div>
      {request.error && <div className="field"><StatusMessage kind="error" message={request.error} /></div>}
      <button type="submit" className="submit-btn" disabled={busy || !village}>
        <i className="ti ti-file-search" /> Fetch Land Details
      </button>
    </form>
  )
}

function PassbookFields({ request }) {
  const [passbookNo, setPassbookNo] = useState('')
  const [aadhaar, setAadhaar] = useState('')
  const { fail, reset, busy } = request

  function submit(e) {
    e.preventDefault()
    if (!passbookNo.trim()) { fail('Please enter the passbook number.'); return }
    if (!/^\d{4}$/.test(aadhaar)) { fail('Please enter exactly the last 4 digits of the Aadhaar number.'); return }
    request.run((signal) => landPassbookPdf({ passbook_no: passbookNo.trim(), aadhaar_last4: aadhaar }, { signal }))
  }

  return (
    <form onSubmit={submit}>
      <div className="field">
        <label>Passbook (PPB) Number <span className="req">*</span><span className="field-hint">On the land passbook, up to 12 characters</span></label>
        <input
          type="text"
          placeholder="e.g. 123456789012"
          value={passbookNo}
          onChange={(e) => { setPassbookNo(e.target.value.replace(/[^A-Za-z0-9]/g, '').slice(0, 12)); reset() }}
          disabled={busy}
          autoComplete="off"
        />
      </div>
      <div className="field">
        <label>Last 4 digits of Aadhaar <span className="req">*</span><span className="field-hint">Of the passbook holder</span></label>
        <input
          type="text"
          inputMode="numeric"
          placeholder="e.g. 1234"
          value={aadhaar}
          onChange={(e) => { setAadhaar(e.target.value.replace(/\D/g, '').slice(-4)); reset() }}  // a pasted full Aadhaar keeps its last 4
          disabled={busy}
          autoComplete="off"
        />
      </div>
      {request.error && <div className="field"><StatusMessage kind="error" message={request.error} /></div>}
      <button type="submit" className="submit-btn" disabled={busy}>
        <i className="ti ti-file-search" /> Fetch Land Details
      </button>
    </form>
  )
}

export default function LandDetailsView() {
  const [mode, setMode] = useState('survey')
  const request = useRequest()
  const { result, busy, cancel } = request

  return (
    <div className="page">
      <div className="page-heading">
        <div className="page-badge">
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#1a6b4a', display: 'inline-block' }} />
          Revenue dept
        </div>
        <h1 className="page-title">Land Details Search</h1>
        <p className="page-subtitle">
          Agricultural land status and ownership from Bhu Bharati — by village + survey/khata number, or by passbook number and the last 4 digits of the owner’s Aadhaar.
        </p>
        <ul className="page-features">
          <li>Live from Bhu Bharati, the Revenue department portal</li>
          <li>By survey and khata number, or by passbook</li>
          <li>The portal’s full record, including land status</li>
        </ul>
      </div>

      <div className="card" style={{ padding: 24 }}>
        <div className="field">
          <label>Search By <span className="req">*</span></label>
          <div className="radio-group" role="radiogroup" aria-label="Search by">
            {MODES.map((m) => (
              <label key={m.value} className={`radio-option${mode === m.value ? ' selected' : ''}`}>
                <input type="radio" name="ld-mode" value={m.value} checked={mode === m.value} disabled={busy}
                  onChange={() => { setMode(m.value); request.reset() }} />
                {m.label}
              </label>
            ))}
          </div>
        </div>
        {mode === 'survey' ? <SurveyFields request={request} /> : <PassbookFields request={request} />}
      </div>

      {result && <DocumentResult key={result.filename} first={result} />}

      <LoaderModal visible={busy} onCancel={cancel} title="Fetching the land record from Bhu Bharati…" />
    </div>
  )
}

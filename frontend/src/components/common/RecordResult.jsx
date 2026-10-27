import StatusMessage from './StatusMessage.jsx'

// The portal's own field names, made readable ("lblOwnerName" → "Owner Name").
const KNOWN_FIELD_LABELS = {
  ptinno: 'PTIN Number',
  owner: 'Owner Name',
  door: 'Door Number',
  assessmentnum: 'Assessment Number',
}

function fieldLabel(key) {
  const stripped = key
    .replace(/^(grd_SearchResult_|ContentPlaceHolder1_)/i, '')
    .replace(/^lbl/i, '')
    .replace(/_\d+$/, '')
  const known = KNOWN_FIELD_LABELS[stripped.toLowerCase()]
  if (known) return known
  const spaced = stripped.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' ').trim()
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : key
}

// A record read off a portal page (GHMC, Bhu Bharati, Adangal): its fields as label/value rows and
// any tables the portal drew, as the portal drew them.
export default function RecordResult({ result }) {
  if (!result.found) {
    return (
      <div className="card result-card">
        <StatusMessage kind="warning" message={result.not_found_messages?.[0] || 'No record found.'} />
      </div>
    )
  }
  const fields = result.raw_fields ? Object.entries(result.raw_fields) : []
  const tables = result.raw_tables_html || []
  return (
    <div className="card result-card">
      <StatusMessage kind="success" message="Record found" />
      {fields.length > 0 && (
        <dl className="record-fields">
          {fields.map(([key, value]) => (
            <div className="record-row" key={key}>
              <dt>{fieldLabel(key)}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {tables.length > 0 && (
        <div className="portal-tables">
          {tables.map((html, i) => <div key={i} dangerouslySetInnerHTML={{ __html: html }} />)}
        </div>
      )}
    </div>
  )
}

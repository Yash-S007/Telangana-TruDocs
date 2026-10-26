const ICONS = {
  info: 'ti-info-circle',
  success: 'ti-circle-check',
  error: 'ti-alert-circle',
  warning: 'ti-alert-triangle',
}

export default function StatusMessage({ kind = 'info', message }) {
  if (!message) return null
  return (
    <div className={`status-msg ${kind}`}>
      <i className={`ti ${ICONS[kind] || ICONS.info}`} />
      <span>{message}</span>
    </div>
  )
}

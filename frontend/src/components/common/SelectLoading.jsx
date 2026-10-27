// A dropdown with a spinner in it while its options load from a government portal.
export default function SelectLoading({ loading, children, ...props }) {
  return (
    <div className="select-wrap">
      <select {...props} disabled={props.disabled || loading}>{children}</select>
      {loading && <span className="select-spinner" aria-label="Loading" />}
    </div>
  )
}

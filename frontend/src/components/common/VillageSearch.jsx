import { useEffect, useRef, useState } from 'react'
import { searchVillages } from '../../utils/api.js'

// The shell's Typeahead look, but the village list (10,000+ villages per portal) is searched on our
// server as you type, not shipped to the browser. Picking a village hands the whole record (its
// district, mandal and village ids) to onSelect; typing again or clearing hands back null.
export default function VillageSearch({ portal, onSelect, disabled = false, placeholder = 'Type village name…' }) {
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState(null)
  const [found, setFound] = useState({ q: '', list: [], failed: false })  // the reply and the text it was for
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(-1)
  const wrapper = useRef(null)

  const q = query.trim()
  const wanted = !selected && q.length >= 2 ? q : ''
  const results = found.q === wanted ? found.list : []
  const searching = wanted !== '' && found.q !== wanted

  useEffect(() => {
    if (!wanted) return
    const ctrl = new AbortController()
    const t = setTimeout(() => {
      searchVillages(portal, wanted, { signal: ctrl.signal })
        .then((list) => { setFound({ q: wanted, list: Array.isArray(list) ? list : [], failed: false }); setHighlighted(-1) })
        .catch((err) => { if (err.name !== 'AbortError') setFound({ q: wanted, list: [], failed: true }) })
    }, 300)
    return () => { clearTimeout(t); ctrl.abort() }
  }, [portal, wanted])

  useEffect(() => {
    function onMouseDown(e) {
      if (!wrapper.current?.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [])

  function pick(v) {
    setSelected(v)
    setQuery(`${v.village} — ${v.mandal}, ${v.district}`)
    setOpen(false)
    onSelect(v)
  }

  function type(value) {
    setQuery(value)
    setOpen(true)
    if (selected) { setSelected(null); onSelect(null) }
  }

  function clear() {
    setQuery('')
    setOpen(false)
    if (selected) { setSelected(null); onSelect(null) }
  }

  function onKeyDown(e) {
    if (!open || results.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlighted((i) => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlighted((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()  // typing then Enter picks the top village, as in the shell's Typeahead
      pick(results[highlighted >= 0 ? highlighted : 0])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="typeahead-wrapper" ref={wrapper}>
      <div className="typeahead-input-row">
        <input
          type="text"
          value={query}
          onChange={(e) => type(e.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
          aria-expanded={open && results.length > 0}
          aria-autocomplete="list"
        />
        {searching && <span className="typeahead-spinner" aria-label="Searching villages" />}
        {query && !searching && !disabled && (
          <button type="button" className="typeahead-clear" onClick={clear} aria-label="Clear">×</button>
        )}
      </div>
      {open && wanted && !searching && (
        <div className="typeahead-results" role="listbox">
          {results.length > 0 ? results.map((v, i) => (
            <div
              key={`${v.village_id ?? v.dmv ?? i}-${i}`}
              className={`typeahead-item${highlighted === i ? ' highlighted' : ''}`}
              role="option"
              aria-selected={highlighted === i}
              onMouseDown={(e) => { e.preventDefault(); pick(v) }}
              onMouseOver={() => setHighlighted(i)}
            >
              <span className="typeahead-item-name">{v.village}</span>
              <span className="typeahead-item-meta">{v.mandal} · {v.district}</span>
            </div>
          )) : (
            <div className="typeahead-empty">{found.failed ? 'Couldn’t search villages right now. Please try again.' : `No villages found for “${q}”`}</div>
          )}
        </div>
      )}
    </div>
  )
}

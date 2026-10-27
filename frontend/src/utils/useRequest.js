import { useCallback, useEffect, useRef, useState } from 'react'

const IDLE = { busy: false, result: null, error: '' }

// One request at a time for a form: `busy` while it runs, then its result or a plain error.
// A newer request, cancel() or reset() abandons the old one, so nothing stale ever lands.
export function useRequest() {
  const [state, setState] = useState(IDLE)
  const current = useRef(null)

  const run = useCallback(async (work) => {
    current.current?.abort()
    const ctrl = (current.current = new AbortController())
    setState({ busy: true, result: null, error: '' })
    try {
      const result = await work(ctrl.signal)
      if (current.current === ctrl) setState({ busy: false, result, error: '' })
    } catch (err) {
      if (current.current === ctrl) setState({ busy: false, result: null, error: err.name === 'AbortError' ? '' : err.message })
    }
  }, [])

  const reset = useCallback(() => {
    current.current?.abort()
    current.current = null
    setState(IDLE)
  }, [])

  const fail = useCallback((error) => {
    current.current?.abort()
    current.current = null
    setState({ busy: false, result: null, error })
  }, [])

  useEffect(() => () => current.current?.abort(), [])  // closed sheet or switched form

  return { ...state, run, reset, cancel: reset, fail }
}

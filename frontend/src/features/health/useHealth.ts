import { useEffect, useState } from 'react'
import { getHealth, type HealthResponse } from '../../api/health'

type HealthState =
  | { kind: 'loading' }
  | { kind: 'ready'; data: HealthResponse }
  | { kind: 'error'; message: string }

export function useHealth() {
  const [state, setState] = useState<HealthState>({ kind: 'loading' })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    getHealth(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ kind: 'ready', data })
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setState({
            kind: 'error',
            message:
              error instanceof Error
                ? error.message
                : 'The API could not be reached.',
          })
        }
      },
    )
    return () => controller.abort()
  }, [attempt])
  function refresh() {
    setState({ kind: 'loading' })
    setAttempt((previous) => previous + 1)
  }
  return { state, refresh }
}

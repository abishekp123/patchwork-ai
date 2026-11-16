import { useHealth } from './useHealth'

export function HealthPanel() {
  const { state, refresh } = useHealth()
  const healthy = state.kind === 'ready' && state.data.status === 'ok'
  const label =
    state.kind === 'loading'
      ? 'Checking connection'
      : state.kind === 'error'
        ? 'API unavailable'
        : healthy
          ? 'All systems operational'
          : 'Service degraded'
  return (
    <section
      aria-labelledby="health-title"
      className="mt-10 overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-stone-100 px-6 py-5 sm:px-8">
        <h2 id="health-title" className="font-medium">
          Service health
        </h2>
        <span className="font-mono text-xs text-stone-500">GET /health</span>
      </div>
      <div className="px-6 py-7 sm:px-8">
        <div
          role="status"
          aria-live="polite"
          className="flex items-center gap-3"
        >
          <span
            aria-hidden="true"
            className={`size-2.5 rounded-full ${state.kind === 'loading' ? 'bg-stone-400' : healthy ? 'bg-emerald-600' : 'bg-amber-500'}`}
          />
          <p className="text-lg font-medium tracking-tight">{label}</p>
        </div>
        {state.kind === 'error' && (
          <div className="mt-3 text-sm leading-6 text-stone-600">
            <p role="alert">{state.message}</p>
            <p>Check that the backend is running, then try again.</p>
          </div>
        )}
        {state.kind === 'ready' && (
          <>
            {state.data.status === 'degraded' && (
              <p className="mt-3 text-sm text-stone-600">
                The API is reachable, but the SQLite check failed.
              </p>
            )}
            <dl className="mt-7 grid grid-cols-1 gap-5 sm:grid-cols-3">
              <div>
                <dt className="text-xs text-stone-500">API service</dt>
                <dd className="mt-2 font-mono text-sm">{state.data.service}</dd>
              </div>
              <div>
                <dt className="text-xs text-stone-500">SQLite</dt>
                <dd className="mt-2 font-mono text-sm">
                  {state.data.checks.database === 'ok'
                    ? 'Connected'
                    : 'Unavailable'}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-stone-500">API version</dt>
                <dd className="mt-2 font-mono text-sm">{state.data.version}</dd>
              </div>
            </dl>
          </>
        )}
        <button
          type="button"
          onClick={refresh}
          disabled={state.kind === 'loading'}
          className="mt-7 rounded-lg bg-stone-900 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-stone-700 disabled:cursor-wait disabled:bg-stone-200 disabled:text-stone-500"
        >
          {state.kind === 'loading' ? 'Checking…' : 'Refresh status'}
        </button>
      </div>
    </section>
  )
}

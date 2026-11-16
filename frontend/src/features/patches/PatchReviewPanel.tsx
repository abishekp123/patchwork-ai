import { useEffect, useState } from 'react'

import { decidePatch, listPatches, type PatchRecord } from '../../api/patches'

export function PatchReviewPanel() {
  const [patches, setPatches] = useState<PatchRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = async () => {
    setLoading(true)
    try {
      const next = await listPatches()
      setPatches(next)
      setError(null)
    } catch (issue) {
      setError(
        issue instanceof Error ? issue.message : 'Unable to load patches.',
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  const review = async (id: string, decision: 'approve' | 'reject') => {
    try {
      const next = await decidePatch(id, {
        decision,
        reviewer: 'human-review',
        reason:
          decision === 'approve'
            ? 'Accepted by the patch review workflow.'
            : 'Rejected by the patch review workflow.',
      })
      setPatches((current) =>
        current.map((item) => (item.id === id ? next : item)),
      )
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : 'Patch review failed.')
    }
  }

  return (
    <section className="mt-10 overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-100 px-6 py-5 sm:px-8">
        <h2 className="text-lg font-semibold tracking-tight">
          Patch review queue
        </h2>
        <button
          type="button"
          onClick={() => void refresh()}
          className="rounded-lg border border-stone-300 px-3 py-1.5 text-sm text-stone-700 transition hover:border-stone-400 hover:bg-stone-50"
        >
          Refresh
        </button>
      </div>
      <div className="space-y-6 px-6 py-7 sm:px-8">
        {loading && (
          <p className="text-sm text-stone-600">Loading patch proposals…</p>
        )}
        {!loading && error && <p className="text-sm text-rose-600">{error}</p>}
        {!loading && !error && patches.length === 0 && (
          <p className="text-sm text-stone-600">
            No patch proposals are available yet.
          </p>
        )}
        {!loading &&
          !error &&
          patches.length > 0 &&
          patches.map((patch) => (
            <article
              key={patch.id}
              className="rounded-xl border border-stone-200 bg-stone-50 p-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-medium text-stone-900">{patch.title}</p>
                  <p className="mt-1 text-xs uppercase tracking-[0.18em] text-stone-500">
                    {patch.status}
                  </p>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void review(patch.id, 'approve')}
                    className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-emerald-500"
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    onClick={() => void review(patch.id, 'reject')}
                    className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm font-medium text-stone-700 transition hover:bg-stone-100"
                  >
                    Reject
                  </button>
                </div>
              </div>
              <p className="mt-3 text-sm leading-6 text-stone-700">
                {patch.summary}
              </p>
              <pre className="mt-4 overflow-x-auto rounded-lg border border-stone-200 bg-white p-3 text-xs leading-6 text-stone-700 whitespace-pre-wrap">
                {patch.diff || 'No diff available.'}
              </pre>
            </article>
          ))}
      </div>
    </section>
  )
}

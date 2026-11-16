import { useCallback, useEffect, useState } from 'react'

import { decidePatch, listPatches, type PatchRecord } from '../../api/patches'
import {
  createPatchVerification,
  getSandboxStatus,
  listPatchVerifications,
  type SandboxStatus,
  type VerificationRecord,
  type VerificationResult,
} from '../../api/verifications'

function summaryLabel(
  value: VerificationRecord['baseline_summary'] | null | undefined,
): string {
  if (!value) return 'Not started'
  if (value.exit_code === null) return 'Timeout'
  if (value.exit_code === 0)
    return `pass (${value.tests_passed}/${value.tests_total})`
  return `exit ${value.exit_code}`
}

export function PatchReviewPanel() {
  const [patches, setPatches] = useState<PatchRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sandboxStatus, setSandboxStatus] = useState<SandboxStatus | null>(null)
  const [verificationByPatch, setVerificationByPatch] = useState<
    Record<string, VerificationRecord[]>
  >({})
  const [verificationResultByPatch, setVerificationResultByPatch] = useState<
    Record<string, VerificationResult | null>
  >({})
  const [inFlightId, setInFlightId] = useState<string | null>(null)

  const refreshVerifications = useCallback(async (patchId: string) => {
    try {
      const records = await listPatchVerifications(patchId)
      setVerificationByPatch((current) => ({ ...current, [patchId]: records }))
      const latest = records[0] ?? null
      setVerificationResultByPatch((current) => ({
        ...current,
        [patchId]: latest ? (latest.comparison ?? null) : null,
      }))
    } catch {
      // Verification details are optional; keep the queue view stable.
    }
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [next, nextSandbox] = await Promise.all([
        listPatches(),
        getSandboxStatus().catch(
          () =>
            ({
              available: false,
              mode: 'fake',
              reason: 'Sandbox status unavailable.',
            }) satisfies SandboxStatus,
        ),
      ])
      setPatches(next)
      setSandboxStatus(nextSandbox)
      setError(null)
      await Promise.all(
        next
          .filter((patch) => patch.status === 'approved')
          .map((patch) => refreshVerifications(patch.id)),
      )
    } catch (issue) {
      setError(
        issue instanceof Error ? issue.message : 'Unable to load patches.',
      )
    } finally {
      setLoading(false)
    }
  }, [refreshVerifications])

  useEffect(() => {
    window.queueMicrotask(() => {
      void refresh()
    })
  }, [refresh])

  useEffect(() => {
    if (!inFlightId) {
      return undefined
    }
    const timer = window.setInterval(() => {
      void refreshVerifications(inFlightId)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [inFlightId, refreshVerifications])

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
      if (next.status === 'approved') {
        await refreshVerifications(id)
      }
    } catch (issue) {
      setError(issue instanceof Error ? issue.message : 'Patch review failed.')
    }
  }

  const verify = async (patch: PatchRecord) => {
    if (patch.status !== 'approved') {
      return
    }
    setInFlightId(patch.id)
    try {
      const record = await createPatchVerification(patch.id, {
        sandbox_mode:
          sandboxStatus?.mode === 'docker' && sandboxStatus.available
            ? 'docker'
            : 'fake',
      })
      setVerificationByPatch((current) => ({
        ...current,
        [patch.id]: [record],
      }))
      await refreshVerifications(patch.id)
    } catch (issue) {
      setError(
        issue instanceof Error
          ? issue.message
          : 'Verification failed to start.',
      )
    } finally {
      setInFlightId(null)
    }
  }

  return (
    <section className="mt-10 overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-100 px-6 py-5 sm:px-8">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">
            Patch review queue
          </h2>
          {sandboxStatus && (
            <p className="mt-1 text-xs text-stone-500">
              Sandbox: {sandboxStatus.available ? 'available' : 'unavailable'}
              {sandboxStatus.reason ? ` · ${sandboxStatus.reason}` : ''}
            </p>
          )}
        </div>
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
          patches.map((patch) => {
            const verificationRecords = verificationByPatch[patch.id] ?? []
            const latestVerification = verificationRecords[0] ?? null
            const latestResult =
              verificationResultByPatch[patch.id] ??
              latestVerification?.comparison ??
              null

            return (
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
                  <div className="flex flex-wrap gap-2">
                    {patch.status === 'approved' && (
                      <button
                        type="button"
                        onClick={() => void verify(patch)}
                        disabled={inFlightId === patch.id}
                        className="rounded-lg bg-violet-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {inFlightId === patch.id ? 'Verifying…' : 'Verify'}
                      </button>
                    )}
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
                {latestVerification && (
                  <div className="mt-4 rounded-xl border border-violet-200 bg-violet-50 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-xs font-medium uppercase tracking-[0.18em] text-violet-700">
                        Verification state
                      </span>
                      <span className="text-xs text-violet-700">
                        {latestVerification.status}
                      </span>
                    </div>
                    {(latestVerification.baseline_summary ||
                      latestVerification.patched_summary) && (
                      <div className="mt-3 grid gap-2 sm:grid-cols-2">
                        <div className="rounded border border-violet-100 bg-white p-2">
                          <p className="text-[10px] uppercase tracking-[0.18em] text-stone-500">
                            Baseline
                          </p>
                          <p className="mt-1 text-sm text-stone-700">
                            {summaryLabel(latestVerification.baseline_summary)}
                          </p>
                        </div>
                        <div className="rounded border border-violet-100 bg-white p-2">
                          <p className="text-[10px] uppercase tracking-[0.18em] text-stone-500">
                            Patched
                          </p>
                          <p className="mt-1 text-sm text-stone-700">
                            {summaryLabel(latestVerification.patched_summary)}
                          </p>
                        </div>
                      </div>
                    )}
                    {latestResult && (
                      <div className="mt-3 rounded border border-violet-100 bg-white p-3">
                        <p className="text-xs font-medium uppercase tracking-[0.18em] text-violet-700">
                          Result
                        </p>
                        <p className="mt-2 text-sm font-medium text-stone-800">
                          {latestResult.status}
                        </p>
                        <p className="mt-1 text-sm text-stone-700">
                          {latestResult.reason}
                        </p>
                        {latestResult.logs.length > 0 && (
                          <details className="mt-3 text-left">
                            <summary className="cursor-pointer text-sm text-stone-700">
                              View logs
                            </summary>
                            <pre className="mt-2 max-h-56 overflow-auto rounded bg-stone-100 p-2 text-xs leading-5 text-stone-700 whitespace-pre-wrap">
                              {latestResult.logs.join('\n') ||
                                'No logs were captured.'}
                            </pre>
                          </details>
                        )}
                      </div>
                    )}
                  </div>
                )}
                <pre className="mt-4 overflow-x-auto rounded-lg border border-stone-200 bg-white p-3 text-xs leading-6 text-stone-700 whitespace-pre-wrap">
                  {patch.diff || 'No diff available.'}
                </pre>
              </article>
            )
          })}
      </div>
    </section>
  )
}

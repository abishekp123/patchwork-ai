import { useCallback, useEffect, useState } from 'react'

import { decidePatch, listPatches, type PatchRecord } from '../../api/patches'
import {
  cancelVerification,
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

export function PatchReviewPanel({
  refreshSignal = 0,
}: {
  refreshSignal?: number
}) {
  const [patches, setPatches] = useState<PatchRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sandboxStatus, setSandboxStatus] = useState<SandboxStatus | null>(null)
  const [sandboxError, setSandboxError] = useState<string | null>(null)
  const [verificationByPatch, setVerificationByPatch] = useState<
    Record<string, VerificationRecord[]>
  >({})
  const [verificationResultByPatch, setVerificationResultByPatch] = useState<
    Record<string, VerificationResult | null>
  >({})
  const [inFlightId, setInFlightId] = useState<string | null>(null)
  const [pollingPatchIds, setPollingPatchIds] = useState<string[]>([])

  const refreshVerifications = useCallback(async (patchId: string) => {
    try {
      const records = await listPatchVerifications(patchId)
      setVerificationByPatch((current) => ({ ...current, [patchId]: records }))
      const latest = records[0] ?? null
      setVerificationResultByPatch((current) => ({
        ...current,
        [patchId]: latest ? (latest.comparison ?? null) : null,
      }))
      return latest
    } catch (issue) {
      setError(
        issue instanceof Error
          ? issue.message
          : 'Unable to refresh verification status.',
      )
      return null
    }
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [next, sandboxResult] = await Promise.allSettled([
        listPatches(),
        getSandboxStatus(),
      ])
      if (next.status === 'rejected') throw next.reason
      const nextSandbox =
        sandboxResult.status === 'fulfilled' ? sandboxResult.value : null
      setSandboxError(
        sandboxResult.status === 'rejected'
          ? sandboxResult.reason instanceof Error
            ? sandboxResult.reason.message
            : 'Sandbox status is unavailable.'
          : null,
      )
      setPatches(next.value)
      setSandboxStatus(nextSandbox)
      setError(null)
      await Promise.all(
        next.value
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
  }, [refresh, refreshSignal])

  useEffect(() => {
    if (pollingPatchIds.length === 0) {
      return undefined
    }
    let active = true
    const timer = window.setInterval(() => {
      void Promise.all(pollingPatchIds.map(refreshVerifications)).then(
        (records) => {
          if (!active) return
          const stillRunning = pollingPatchIds.filter((_, index) => {
            const record = records[index]
            return (
              record !== null &&
              record !== undefined &&
              !['COMPLETED', 'FAILED', 'CANCELLED'].includes(record.status)
            )
          })
          setPollingPatchIds(stillRunning)
        },
      )
    }, 1500)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [pollingPatchIds, refreshVerifications])

  const review = async (id: string, decision: 'approve' | 'reject') => {
    if (inFlightId) return
    setInFlightId(id)
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
    } finally {
      setInFlightId(null)
    }
  }

  const verify = async (patch: PatchRecord) => {
    if (
      patch.status !== 'approved' ||
      sandboxStatus?.mode !== 'docker' ||
      !sandboxStatus.available ||
      inFlightId
    ) {
      return
    }
    setInFlightId(patch.id)
    setPollingPatchIds((current) =>
      current.includes(patch.id) ? current : [...current, patch.id],
    )
    try {
      const record = await createPatchVerification(patch.id, {
        sandbox_mode: 'docker',
      })
      setVerificationByPatch((current) => ({
        ...current,
        [patch.id]: [record, ...(current[patch.id] ?? [])],
      }))
      const latest = await refreshVerifications(patch.id)
      if (
        latest &&
        ['COMPLETED', 'FAILED', 'CANCELLED'].includes(latest.status)
      ) {
        setPollingPatchIds((current) =>
          current.filter((identifier) => identifier !== patch.id),
        )
      }
    } catch (issue) {
      setPollingPatchIds((current) =>
        current.filter((identifier) => identifier !== patch.id),
      )
      setError(
        issue instanceof Error
          ? issue.message
          : 'Verification failed to start.',
      )
    } finally {
      setInFlightId(null)
    }
  }

  const cancel = async (id: string) => {
    if (inFlightId) return
    setInFlightId(id)
    try {
      await cancelVerification(id)
      const patchId = Object.entries(verificationByPatch).find(([, records]) =>
        records.some((record) => record.id === id),
      )?.[0]
      if (patchId) await refreshVerifications(patchId)
      if (patchId) {
        setPollingPatchIds((current) =>
          current.filter((identifier) => identifier !== patchId),
        )
      }
    } catch (issue) {
      setError(
        issue instanceof Error
          ? issue.message
          : 'Verification cancellation failed.',
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
          <p className="mt-1 text-xs text-stone-500">
            {sandboxStatus?.mode === 'docker'
              ? `Docker sandbox: ${sandboxStatus.available ? 'available' : 'unavailable'}`
              : sandboxStatus?.mode === 'fake'
                ? 'Fake adapter is test-only; Docker verification is disabled.'
                : 'Sandbox status unavailable'}
            {sandboxStatus?.reason
              ? ` · ${sandboxStatus.reason}`
              : sandboxError
                ? ` · ${sandboxError}`
                : ''}
          </p>
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
        {!loading && error && (
          <p role="alert" className="text-sm text-rose-600">
            {error}
          </p>
        )}
        {!loading && !error && patches.length === 0 && (
          <p className="text-sm text-stone-600">
            No patch proposals are available yet.
          </p>
        )}
        {!loading &&
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
                        disabled={
                          inFlightId === patch.id ||
                          sandboxStatus?.mode !== 'docker' ||
                          !sandboxStatus.available
                        }
                        title={
                          sandboxStatus?.mode === 'fake'
                            ? 'Docker sandbox is required for verification.'
                            : (sandboxStatus?.reason ?? undefined)
                        }
                        className="rounded-lg bg-violet-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {inFlightId === patch.id ? 'Verifying…' : 'Verify'}
                      </button>
                    )}
                    {patch.status === 'pending_review' && (
                      <>
                        <button
                          type="button"
                          onClick={() => void review(patch.id, 'approve')}
                          disabled={inFlightId !== null}
                          className="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-emerald-500 disabled:opacity-50"
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          onClick={() => void review(patch.id, 'reject')}
                          disabled={inFlightId !== null}
                          className="rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm font-medium text-stone-700 transition hover:bg-stone-100 disabled:opacity-50"
                        >
                          Reject
                        </button>
                      </>
                    )}
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
                        {latestVerification.sandbox_mode === 'docker'
                          ? latestVerification.status
                          : 'SIMULATED — not Docker verified'}
                      </span>
                    </div>
                    {latestVerification.error_code && (
                      <p role="status" className="mt-2 text-sm text-rose-800">
                        {latestVerification.error_code === 'interrupted'
                          ? 'Interrupted by a server restart. Verify again to retry after cleanup.'
                          : `Verification stopped: ${latestVerification.error_code}`}
                      </p>
                    )}
                    {latestVerification &&
                      !['COMPLETED', 'FAILED', 'CANCELLED'].includes(
                        latestVerification.status,
                      ) && (
                        <button
                          type="button"
                          onClick={() => void cancel(latestVerification.id)}
                          disabled={inFlightId === latestVerification.id}
                          className="mt-3 rounded-lg border border-rose-300 bg-white px-3 py-1.5 text-xs font-medium text-rose-800 disabled:opacity-50"
                        >
                          Cancel verification
                        </button>
                      )}
                    {latestVerification.sandbox_mode === 'docker' &&
                      (latestVerification.baseline_summary ||
                        latestVerification.patched_summary) && (
                        <div className="mt-3 grid gap-2 sm:grid-cols-2">
                          <div className="rounded border border-violet-100 bg-white p-2">
                            <p className="text-[10px] uppercase tracking-[0.18em] text-stone-500">
                              Baseline
                            </p>
                            <p className="mt-1 text-sm text-stone-700">
                              {summaryLabel(
                                latestVerification.baseline_summary,
                              )}
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
                    {latestResult &&
                      latestVerification.sandbox_mode === 'docker' && (
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

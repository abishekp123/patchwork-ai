import { afterEach, describe, expect, it, vi } from 'vitest'

import { getDashboard } from './dashboard'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('getDashboard', () => {
  it('returns persisted dashboard metrics and activity', async () => {
    const summary = {
      ready_repositories: 2,
      investigations: 3,
      pending_patches: 1,
      approved_patches: 1,
      active_verifications: 1,
      completed_verifications: 4,
      recent_activity: [
        {
          kind: 'patch',
          id: 'patch-id',
          repository_id: 'repository-id',
          status: 'pending_review',
          updated_at: '2026-01-01T00:00:00Z',
          label: 'Fix calculation',
        },
      ],
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => summary,
      })),
    )

    await expect(getDashboard()).resolves.toEqual(summary)
  })

  it('rejects malformed summaries instead of presenting fabricated metrics', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          ready_repositories: 2,
          investigations: 0,
          pending_patches: 0,
          approved_patches: 0,
          active_verifications: 0,
          completed_verifications: 0,
          recent_activity: [{ kind: 'unknown' }],
        }),
      })),
    )

    await expect(getDashboard()).rejects.toThrow(
      'The API returned an invalid dashboard response.',
    )
  })
})

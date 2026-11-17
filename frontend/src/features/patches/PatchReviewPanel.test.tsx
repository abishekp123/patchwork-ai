import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { PatchReviewPanel } from './PatchReviewPanel'

describe('PatchReviewPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders patch proposals and review actions', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          items: [
            {
              id: 'patch-1',
              repository_id: 'a'.repeat(64),
              commit_sha: 'b'.repeat(40),
              investigation_id: null,
              status: 'pending_review',
              title: 'Fix null handling',
              summary: 'Guard the code path before dereference.',
              diff: '--- a/example.py\n+++ b/example.py\n@@\n-value\n+safe',
              evidence_ids: ['abc123'],
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
              reviewed_at: null,
              reviewer: null,
              decision_reason: null,
              error_code: null,
            },
          ],
        }),
      }),
    )

    render(<PatchReviewPanel />)

    await waitFor(() => {
      expect(screen.getByText('Fix null handling')).toBeInTheDocument()
    })

    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument()
  })

  it('shows loading and empty states before data arrives', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [] }),
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<PatchReviewPanel />)

    expect(screen.getByText('Loading patch proposals…')).toBeInTheDocument()

    await waitFor(() => {
      expect(
        screen.getByText('No patch proposals are available yet.'),
      ).toBeInTheDocument()
    })
  })

  it('shows API failures when the patch list cannot be loaded', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
      }),
    )

    render(<PatchReviewPanel />)

    await waitFor(() => {
      expect(
        screen.getByText('Patch listing failed (HTTP 500).'),
      ).toBeInTheDocument()
    })
  })

  it('submits approve and reject decisions and updates the review state', async () => {
    const listMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          items: [
            {
              id: 'patch-1',
              repository_id: 'a'.repeat(64),
              commit_sha: 'b'.repeat(40),
              investigation_id: null,
              status: 'pending_review',
              title: 'Fix null handling',
              summary: 'Guard the code path before dereference.',
              diff: '--- a/example.py\n+++ b/example.py\n@@\n-value\n+safe',
              evidence_ids: ['abc123'],
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
              reviewed_at: null,
              reviewer: null,
              decision_reason: null,
              error_code: null,
            },
          ],
        }),
      })
      .mockResolvedValue({
        ok: true,
        json: async () => ({ items: [] }),
      })

    const reviewMock = vi
      .fn()
      .mockImplementation(async (_url: string, init?: RequestInit) => {
        const body = JSON.parse(init?.body as string)
        return {
          ok: true,
          json: async () => ({
            patch: {
              ...{
                id: 'patch-1',
                repository_id: 'a'.repeat(64),
                commit_sha: 'b'.repeat(40),
                investigation_id: null,
                status: body.decision === 'approve' ? 'approved' : 'rejected',
                title: 'Fix null handling',
                summary: 'Guard the code path before dereference.',
                diff: '--- a/example.py\n+++ b/example.py\n@@\n-value\n+safe',
                evidence_ids: ['abc123'],
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
                reviewed_at: '2026-01-02T00:00:00Z',
                reviewer: 'human-review',
                decision_reason: body.reason,
                error_code: null,
              },
            },
          }),
        }
      })

    vi.stubGlobal(
      'fetch',
      vi.fn((input: string | URL | Request, init?: RequestInit) => {
        if (
          typeof input === 'string' &&
          (input.includes('/approve') || input.includes('/reject'))
        ) {
          return reviewMock(input, init)
        }
        return listMock()
      }),
    )

    render(<PatchReviewPanel />)

    await waitFor(() => {
      expect(screen.getByText('Fix null handling')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => {
      expect(screen.getByText('approved')).toBeInTheDocument()
    })

    expect(
      screen.queryByRole('button', { name: 'Reject' }),
    ).not.toBeInTheDocument()
  })

  it('submits a rejection decision for a pending patch', async () => {
    const patch = {
      id: 'patch-2',
      repository_id: 'a'.repeat(64),
      commit_sha: 'b'.repeat(40),
      investigation_id: null,
      status: 'pending_review',
      title: 'Rejectable patch',
      summary: 'Review this proposed change.',
      diff: '+unsafe',
      evidence_ids: [],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      reviewed_at: null,
      reviewer: null,
      decision_reason: null,
      error_code: null,
    }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/patches')
          return { ok: true, json: async () => ({ items: [patch] }) }
        if (url.endsWith('/reject')) {
          expect(JSON.parse(init?.body as string).decision).toBe('reject')
          return {
            ok: true,
            json: async () => ({
              patch: { ...patch, status: 'rejected', reviewer: 'human-review' },
            }),
          }
        }
        return {
          ok: false,
          status: 503,
          json: async () => ({ error: { message: 'Sandbox unavailable.' } }),
        }
      }),
    )

    render(<PatchReviewPanel />)
    fireEvent.click(await screen.findByRole('button', { name: 'Reject' }))

    expect(await screen.findByText('rejected')).toBeInTheDocument()
  })

  it('never runs a fake sandbox as a substitute for Docker verification', async () => {
    const fetchMock = vi.fn(
      async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/patches')
          return {
            ok: true,
            json: async () => ({
              items: [
                {
                  id: 'patch-approved',
                  repository_id: 'a'.repeat(64),
                  commit_sha: 'b'.repeat(40),
                  investigation_id: null,
                  status: 'approved',
                  title: 'Reviewed patch',
                  summary: 'Safe change.',
                  diff: '+safe',
                  evidence_ids: [],
                  created_at: '2026-01-01T00:00:00Z',
                  updated_at: '2026-01-01T00:00:00Z',
                  reviewed_at: '2026-01-01T00:00:00Z',
                  reviewer: 'human',
                  decision_reason: null,
                  error_code: null,
                },
              ],
            }),
          }
        if (url === '/api/verification/sandbox-status')
          return {
            ok: true,
            json: async () => ({
              available: true,
              mode: 'fake',
              reason: 'test-only',
            }),
          }
        if (
          url === '/api/patches/patch-approved/verifications' &&
          init?.method === 'POST'
        )
          return { ok: true, json: async () => ({ verification: {} }) }
        return { ok: true, json: async () => ({ items: [] }) }
      },
    )
    vi.stubGlobal('fetch', fetchMock)

    render(<PatchReviewPanel />)

    const verifyButton = await screen.findByRole('button', { name: 'Verify' })
    expect(verifyButton).toBeDisabled()
    fireEvent.click(verifyButton)
    expect(
      fetchMock.mock.calls.some(
        ([url, init]) =>
          url === '/api/patches/patch-approved/verifications' &&
          init?.method === 'POST',
      ),
    ).toBe(false)
    expect(screen.getByText(/Fake adapter is test-only/)).toBeInTheDocument()
  })

  it('shows real Docker verification summaries and comparisons', async () => {
    const patch = {
      id: 'patch-approved',
      repository_id: 'a'.repeat(64),
      commit_sha: 'b'.repeat(40),
      investigation_id: null,
      status: 'approved',
      title: 'Reviewed patch',
      summary: 'Safe change.',
      diff: '+safe',
      evidence_ids: [],
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
      reviewed_at: '2026-01-01T00:00:00Z',
      reviewer: 'human',
      decision_reason: null,
      error_code: null,
    }
    const summary = {
      exit_code: 0,
      duration_ms: 20,
      stdout_truncated: false,
      stderr_truncated: false,
      stdout_bytes: 20,
      stderr_bytes: 0,
      tests_total: 1,
      tests_passed: 1,
      tests_failed: 0,
      tests_skipped: 0,
      error_code: null,
    }
    const verification = {
      id: 'verification-1',
      patch_id: patch.id,
      repository_id: patch.repository_id,
      commit_sha: patch.commit_sha,
      status: 'COMPLETED',
      sandbox_mode: 'docker',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:01Z',
      started_at: '2026-01-01T00:00:00Z',
      completed_at: '2026-01-01T00:00:01Z',
      baseline_summary: summary,
      patched_summary: summary,
      comparison: {
        status: 'IMPROVED',
        classification: 'improved',
        reason: 'The patched test passed; baseline failed.',
        baseline: summary,
        patched: summary,
        diff_summary: {},
        logs: [],
      },
      error_code: null,
      execution_logs: [],
    }
    const fetchMock = vi.fn(
      async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/patches')
          return { ok: true, json: async () => ({ items: [patch] }) }
        if (url === '/api/verification/sandbox-status')
          return {
            ok: true,
            json: async () => ({ available: true, mode: 'docker' }),
          }
        if (url === `/api/patches/${patch.id}/verifications`) {
          if (init?.method === 'POST')
            return { ok: true, json: async () => ({ verification }) }
          return {
            ok: true,
            json: async () => ({ items: [verification] }),
          }
        }
        throw new Error(`Unexpected API request: ${url}`)
      },
    )
    vi.stubGlobal('fetch', fetchMock)

    render(<PatchReviewPanel />)
    fireEvent.click(await screen.findByRole('button', { name: 'Verify' }))

    expect(await screen.findByText('IMPROVED')).toBeInTheDocument()
    expect(screen.getAllByText('pass (1/1)')).toHaveLength(2)
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/patches/${patch.id}/verifications`,
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"sandbox_mode":"docker"'),
      }),
    )
  })
})

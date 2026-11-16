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

    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))

    await waitFor(() => {
      expect(screen.getByText('rejected')).toBeInTheDocument()
    })
  })
})

import { render, screen, waitFor } from '@testing-library/react'
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
})

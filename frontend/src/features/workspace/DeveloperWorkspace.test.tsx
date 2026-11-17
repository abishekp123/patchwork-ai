import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DeveloperWorkspace } from './DeveloperWorkspace'

const repositoryId = 'a'.repeat(64)
const investigationId = 'b'.repeat(32)
const evidenceId = 'evidence-1'

function response(data: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    json: async () => data,
  }
}

const repository = {
  id: repositoryId,
  normalized_url: 'https://github.com/example/project',
  commit_sha: 'c'.repeat(40),
  status: 'ready',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  indexed_at: '2026-01-01T00:00:00Z',
  file_count: 1,
  symbol_count: 1,
  import_count: 0,
}

const file = {
  path: 'src/bug.py',
  content_hash: 'd'.repeat(64),
  size_bytes: 32,
  encoding: 'utf-8',
  line_count: 2,
  has_errors: false,
}

const completedInvestigation = {
  id: investigationId,
  repository_id: repositoryId,
  commit_sha: repository.commit_sha,
  description: 'Investigate the incorrect result.',
  status: 'COMPLETED',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:01Z',
  completed_at: '2026-01-01T00:00:01Z',
  error_code: null,
  report: {
    summary: 'The function returns the wrong value.',
    facts: [
      {
        statement: 'The function returns 1.',
        evidence_ids: [evidenceId],
      },
    ],
    hypotheses: [],
    next_steps: [],
    limitations: ['No execution was performed.'],
    evidence: [
      {
        evidence_id: evidenceId,
        repository_id: repositoryId,
        commit_sha: repository.commit_sha,
        path: file.path,
        start_line: 1,
        end_line: 2,
      },
    ],
  },
}

describe('DeveloperWorkspace', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('browses indexed source and follows evidence from a completed investigation', async () => {
    const fetchMock = vi.fn(
      async (input: string | URL | Request, init?: RequestInit) => {
        const url = String(input)
        if (url === '/api/dashboard')
          return response({
            ready_repositories: 1,
            investigations: 1,
            pending_patches: 1,
            approved_patches: 0,
            active_verifications: 0,
            completed_verifications: 0,
            recent_activity: [
              {
                kind: 'patch',
                id: 'patch-1',
                repository_id: repositoryId,
                status: 'pending_review',
                updated_at: '2026-01-01T00:00:02Z',
                label: 'Validated repair draft',
              },
            ],
          })
        if (url === '/api/repositories')
          return response({ items: [repository], total: 1 })
        if (url === '/api/investigations/provider-status')
          return response({
            available: true,
            provider: 'openai',
            model: 'test-model',
            reason: null,
          })
        if (url.includes('/files?'))
          return response({ items: [file], total: 1 })
        if (url.includes('/investigations?'))
          return response({ items: [], total: 0 })
        if (url.includes('/content?'))
          return response({
            repository_id: repositoryId,
            commit_sha: repository.commit_sha,
            path: file.path,
            content_hash: file.content_hash,
            start_line: 1,
            end_line: 2,
            total_lines: 2,
            content: 'def bug():\n    return 1',
          })
        if (url.endsWith('/steps?limit=100'))
          return response({
            items: [
              { sequence: 1, created_at: '2026-01-01T00:00:00Z', data: {} },
            ],
            total: 1,
          })
        if (url === '/api/investigations' && init?.method === 'POST')
          return response({
            investigation: {
              ...completedInvestigation,
              status: 'CREATED',
              report: null,
            },
          })
        if (url === '/api/patches' && init?.method === 'POST')
          return response({
            patch: {
              id: 'patch-1',
              repository_id: repositoryId,
              commit_sha: repository.commit_sha,
              investigation_id: investigationId,
              status: 'pending_review',
              title: 'Validated repair draft',
              summary: 'A snapshot-validated change.',
              diff: '--- a/src/bug.py\n+++ b/src/bug.py',
              evidence_ids: [evidenceId],
              created_at: '2026-01-01T00:00:02Z',
              updated_at: '2026-01-01T00:00:02Z',
              reviewed_at: null,
              reviewer: null,
              decision_reason: null,
              error_code: null,
            },
          })
        if (url.endsWith(`/investigations/${investigationId}`))
          return response(completedInvestigation)
        throw new Error(`Unexpected API request: ${url}`)
      },
    )
    vi.stubGlobal('fetch', fetchMock)

    render(<DeveloperWorkspace />)

    expect(await screen.findByText('Pending review')).toBeInTheDocument()
    expect(screen.getByText('Validated repair draft')).toBeInTheDocument()
    expect(await screen.findByText('def bug():')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Describe the bug or question'), {
      target: { value: 'Investigate the incorrect result.' },
    })
    fireEvent.click(
      screen.getByRole('button', { name: 'Investigate snapshot' }),
    )

    expect(
      await screen.findByText('The function returns the wrong value.'),
    ).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: 'Propose evidence-backed patch' }),
    )
    expect(
      await screen.findByText('Validated repair draft'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Open patch review' }),
    ).toHaveAttribute('href', '#patch-review')
    const citation = screen.getByRole('button', {
      name: `${file.path}:1–2`,
    })
    fireEvent.click(citation)
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining(
          `/files/${encodeURIComponent(file.path)}/content`,
        ),
        expect.objectContaining({ cache: 'no-store' }),
      )
    })
  })

  it('shows backend errors and disables investigations when the provider is unavailable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: string | URL | Request) => {
        if (String(input) === '/api/repositories') {
          return response(
            { error: { message: 'Repository service is unavailable.' } },
            false,
            503,
          )
        }
        return response({
          available: false,
          provider: 'openai',
          model: 'test-model',
          reason: 'Configure OPENAI_API_KEY.',
        })
      }),
    )

    render(<DeveloperWorkspace />)

    expect(
      await screen.findByText('Repository service is unavailable.'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Investigate snapshot' }),
    ).toBeDisabled()
    expect(screen.getByText('Configure OPENAI_API_KEY.')).toBeInTheDocument()
  })
})

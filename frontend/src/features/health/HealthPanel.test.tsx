import { StrictMode } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { HealthPanel } from './HealthPanel'
import { degradedResponse, healthyResponse } from '../../test/fixtures'

describe('service health panel', () => {
  it('shows loading followed by the live API fields in StrictMode', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async () => Response.json(healthyResponse)),
    )
    render(
      <StrictMode>
        <HealthPanel />
      </StrictMode>,
    )
    expect(screen.getByRole('status')).toHaveTextContent('Checking connection')
    expect(screen.getByRole('button')).toBeDisabled()
    expect(
      await screen.findByText('All systems operational'),
    ).toBeInTheDocument()
    expect(screen.getByText('patchwork-ai')).toBeInTheDocument()
    expect(screen.getByText('Connected')).toBeInTheDocument()
    expect(screen.getByText('0.1.0')).toBeInTheDocument()
  })
  it('shows a connection failure and recovers after refresh', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockRejectedValueOnce(new TypeError('Failed to fetch'))
        .mockResolvedValueOnce(Response.json(healthyResponse)),
    )
    render(<HealthPanel />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Failed to fetch',
    )
    expect(screen.getByRole('status')).toHaveTextContent('API unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Refresh status' }))
    expect(
      await screen.findByText('All systems operational'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
  it('distinguishes a database failure from an unreachable API', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(Response.json(degradedResponse, { status: 503 })),
    )
    render(<HealthPanel />)
    expect(await screen.findByText('Service degraded')).toBeInTheDocument()
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh status' })).toBeEnabled()
  })
})

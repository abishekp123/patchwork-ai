import { afterEach, describe, expect, it, vi } from 'vitest'
import { getHealth } from './health'
import { degradedResponse, healthyResponse } from '../test/fixtures'

afterEach(() => vi.useRealTimers())

describe('health API client', () => {
  it.each([
    [200, healthyResponse],
    [503, degradedResponse],
  ])('accepts the documented HTTP %s response', async (status, data) => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json(data, { status }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(getHealth(new AbortController().signal)).resolves.toEqual(data)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/health',
      expect.objectContaining({ cache: 'no-store' }),
    )
  })
  it.each([
    [200, { status: 'ok' }],
    [200, degradedResponse],
    [503, healthyResponse],
  ])('rejects malformed or inconsistent response %#', async (status, data) => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(Response.json(data, { status })),
    )
    await expect(getHealth(new AbortController().signal)).rejects.toThrow(
      'unexpected health response',
    )
  })
  it('rejects unexpected HTTP errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('Bad gateway', { status: 502 })),
    )
    await expect(getHealth(new AbortController().signal)).rejects.toThrow(
      'HTTP 502',
    )
  })
  it('rejects non-JSON responses', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('<html>Not an API</html>')),
    )
    await expect(getHealth(new AbortController().signal)).rejects.toThrow()
  })
  it('times out an unresponsive API', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, options: RequestInit) =>
          new Promise((_resolve, reject) => {
            options.signal?.addEventListener('abort', () =>
              reject(new DOMException('Aborted', 'AbortError')),
            )
          }),
      ),
    )
    const result = expect(
      getHealth(new AbortController().signal),
    ).rejects.toThrow('within 5 seconds')
    await vi.advanceTimersByTimeAsync(5000)
    await result
    expect(vi.getTimerCount()).toBe(0)
  })
  it('forwards caller cancellation and clears the timeout', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, options: RequestInit) =>
          new Promise((_resolve, reject) => {
            options.signal?.addEventListener('abort', () =>
              reject(new DOMException('Aborted', 'AbortError')),
            )
          }),
      ),
    )
    const controller = new AbortController()
    const result = expect(getHealth(controller.signal)).rejects.toThrow(
      'Aborted',
    )
    controller.abort()
    await result
    expect(vi.getTimerCount()).toBe(0)
  })
})

export interface HealthResponse {
  status: 'ok' | 'degraded'
  service: 'patchwork-ai'
  version: string
  checks: { database: 'ok' | 'error' }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isHealthResponse(value: unknown): value is HealthResponse {
  return (
    isRecord(value) &&
    value.service === 'patchwork-ai' &&
    typeof value.version === 'string' &&
    value.version.trim().length > 0 &&
    isRecord(value.checks) &&
    ((value.status === 'ok' && value.checks.database === 'ok') ||
      (value.status === 'degraded' && value.checks.database === 'error'))
  )
}

export async function getHealth(signal: AbortSignal): Promise<HealthResponse> {
  const controller = new AbortController()
  const cancel = () => controller.abort()
  signal.addEventListener('abort', cancel, { once: true })
  if (signal.aborted) cancel()
  const timeout = setTimeout(() => controller.abort(), 5000)
  try {
    const response = await fetch('/api/health', {
      signal: controller.signal,
      headers: { Accept: 'application/json' },
      cache: 'no-store',
    })
    if (response.status !== 200 && response.status !== 503) {
      throw new Error(`Health request failed (HTTP ${response.status}).`)
    }
    const data: unknown = await response.json()
    if (
      !isHealthResponse(data) ||
      (response.status === 200) !== (data.status === 'ok')
    ) {
      throw new Error('The API returned an unexpected health response.')
    }
    return data
  } catch (error) {
    if (controller.signal.aborted && !signal.aborted) {
      throw new Error('The API did not respond within 5 seconds.')
    }
    throw error
  } finally {
    clearTimeout(timeout)
    signal.removeEventListener('abort', cancel)
  }
}

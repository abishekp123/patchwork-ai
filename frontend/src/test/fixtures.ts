import type { HealthResponse } from '../api/health'

export const healthyResponse: HealthResponse = {
  status: 'ok',
  service: 'patchwork-ai',
  version: '0.1.0',
  checks: { database: 'ok' },
}
export const degradedResponse: HealthResponse = {
  ...healthyResponse,
  status: 'degraded',
  checks: { database: 'error' },
}

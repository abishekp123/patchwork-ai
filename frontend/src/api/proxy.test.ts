// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { rewriteApiPath } from '../../vite.config'

describe('development and preview API proxy', () => {
  it.each(['/api/health', '/api/health?probe=1'])(
    'forwards %s to the unprefixed health endpoint',
    (path) => expect(rewriteApiPath(path)).toBe(path.replace('/api', '')),
  )
  it.each([
    '/api/repositories',
    '/api/investigations',
    '/api/patches',
    '/api/verification/sandbox-status',
    '/api/dashboard',
  ])('preserves the API prefix for %s', (path) => {
    expect(rewriteApiPath(path)).toBe(path)
  })
})

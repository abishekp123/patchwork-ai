export type VerificationStatus =
  | 'CREATED'
  | 'PREPARING'
  | 'RUNNING_BASELINE'
  | 'RUNNING_PATCHED'
  | 'COMPARING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

export interface VerificationSummary {
  exit_code: number | null
  duration_ms: number
  stdout_truncated: boolean
  stderr_truncated: boolean
  stdout_bytes: number
  stderr_bytes: number
  tests_total: number
  tests_passed: number
  tests_failed: number
  tests_skipped: number
  error_code: string | null
}

export interface VerificationResult {
  status:
    | 'IMPROVED'
    | 'REGRESSED'
    | 'UNCHANGED'
    | 'INCONCLUSIVE'
    | 'FAILED'
    | 'SANDBOX_UNAVAILABLE'
  classification: string
  reason: string
  baseline: VerificationSummary
  patched: VerificationSummary
  diff_summary: Record<string, number>
  logs: string[]
}

export interface VerificationRecord {
  id: string
  patch_id: string
  repository_id: string
  commit_sha: string
  status: VerificationStatus
  sandbox_mode: string
  created_at: string
  updated_at: string
  started_at: string | null
  completed_at: string | null
  baseline_summary: VerificationSummary | null
  patched_summary: VerificationSummary | null
  comparison: VerificationResult | null
  error_code: string | null
  execution_logs: string[]
}

export interface SandboxStatus {
  available: boolean
  mode: 'fake' | 'docker'
  reason?: string | null
}

function isVerificationRecord(value: unknown): value is VerificationRecord {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.id === 'string' &&
    typeof candidate.patch_id === 'string' &&
    typeof candidate.status === 'string'
  )
}

export async function getSandboxStatus(): Promise<SandboxStatus> {
  const response = await fetch('/api/verification/sandbox-status', {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`Sandbox status check failed (HTTP ${response.status}).`)
  }
  const data: unknown = await response.json()
  if (typeof data !== 'object' || data === null) {
    throw new Error('The API returned an invalid sandbox status response.')
  }
  const candidate = data as Record<string, unknown>
  if (
    typeof candidate.available !== 'boolean' ||
    (candidate.mode !== 'fake' && candidate.mode !== 'docker')
  ) {
    throw new Error('The API returned an invalid sandbox status response.')
  }
  return {
    available: candidate.available,
    mode: candidate.mode,
    reason: typeof candidate.reason === 'string' ? candidate.reason : null,
  }
}

export async function createPatchVerification(
  patchId: string,
  payload?: {
    sandbox_mode?: 'docker'
    baseline_command?: string
    patched_command?: string
  },
): Promise<VerificationRecord> {
  const response = await fetch(`/api/patches/${patchId}/verifications`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      sandbox_mode: payload?.sandbox_mode ?? 'docker',
      baseline_command: payload?.baseline_command ?? 'python -m pytest -q',
      patched_command: payload?.patched_command ?? 'python -m pytest -q',
    }),
  })
  if (!response.ok) {
    throw new Error(`Verification request failed (HTTP ${response.status}).`)
  }
  const data: unknown = await response.json()
  if (
    !isVerificationRecord((data as { verification?: unknown })?.verification)
  ) {
    throw new Error('The API returned an invalid verification response.')
  }
  return (data as { verification: VerificationRecord }).verification
}

export async function listPatchVerifications(
  patchId: string,
): Promise<VerificationRecord[]> {
  const response = await fetch(`/api/patches/${patchId}/verifications`, {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`Verification listing failed (HTTP ${response.status}).`)
  }
  const data: unknown = await response.json()
  if (
    typeof data !== 'object' ||
    data === null ||
    !Array.isArray((data as { items?: unknown }).items)
  ) {
    throw new Error('The API returned an invalid verification list response.')
  }
  return (data as { items: unknown[] }).items.filter(isVerificationRecord)
}

export async function getVerification(id: string): Promise<VerificationRecord> {
  const response = await fetch(`/api/verifications/${id}`, {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`Verification lookup failed (HTTP ${response.status}).`)
  }
  const data: unknown = await response.json()
  if (
    !isVerificationRecord((data as { verification?: unknown })?.verification)
  ) {
    throw new Error('The API returned an invalid verification record.')
  }
  return (data as { verification: VerificationRecord }).verification
}

export async function getVerificationResults(
  id: string,
): Promise<VerificationResult | null> {
  const response = await fetch(`/api/verifications/${id}/results`, {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(
      `Verification results lookup failed (HTTP ${response.status}).`,
    )
  }
  const data: unknown = await response.json()
  if (typeof data !== 'object' || data === null) {
    throw new Error('The API returned invalid verification results.')
  }
  const candidate = data as Record<string, unknown>
  if (candidate.result === null) {
    return null
  }
  if (typeof candidate.result !== 'object' || candidate.result === null) {
    throw new Error('The API returned an invalid verification result.')
  }
  return candidate.result as VerificationResult
}

export async function cancelVerification(
  id: string,
): Promise<VerificationRecord> {
  const response = await fetch(`/api/verifications/${id}/cancel`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error(
      `Verification cancellation failed (HTTP ${response.status}).`,
    )
  }
  const data: unknown = await response.json()
  if (
    !isVerificationRecord((data as { verification?: unknown })?.verification)
  ) {
    throw new Error('The API returned an invalid cancellation response.')
  }
  return (data as { verification: VerificationRecord }).verification
}

export function verificationSummaryLabel(
  summary: VerificationSummary | null | undefined,
): string {
  if (!summary) return 'Not started'
  if (summary.exit_code === 0)
    return `Success (${summary.tests_passed}/${summary.tests_total})`
  if (summary.exit_code === null) return 'Timeout'
  return `Exit ${summary.exit_code}`
}

export function isVerificationSuccessful(
  result: VerificationResult | null | undefined,
): boolean {
  if (!result) return false
  return result.status === 'UNCHANGED' || result.status === 'IMPROVED'
}

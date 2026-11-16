export type PatchStatus =
  'draft' | 'pending_review' | 'approved' | 'rejected' | 'failed' | 'invalid'

export interface PatchChange {
  path: string
  before: string
  after: string
  reason: string
}

export interface PatchRecord {
  id: string
  repository_id: string
  commit_sha: string
  investigation_id: string | null
  status: PatchStatus
  title: string
  summary: string
  diff: string
  evidence_ids: string[]
  created_at: string
  updated_at: string
  reviewed_at: string | null
  reviewer: string | null
  decision_reason: string | null
  error_code: string | null
}

export interface PatchRequest {
  repository_id: string
  description: string
  investigation_id?: string | null
  evidence_ids?: string[]
}

export interface PatchDecision {
  decision: 'approve' | 'reject'
  reviewer: string
  reason?: string
}

function isPatchRecord(value: unknown): value is PatchRecord {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.id === 'string' &&
    typeof candidate.repository_id === 'string' &&
    typeof candidate.commit_sha === 'string' &&
    typeof candidate.status === 'string' &&
    typeof candidate.title === 'string' &&
    typeof candidate.summary === 'string' &&
    typeof candidate.diff === 'string' &&
    Array.isArray(candidate.evidence_ids)
  )
}

function isPatchPage(value: unknown): value is { items: PatchRecord[] } {
  return (
    typeof value === 'object' &&
    value !== null &&
    Array.isArray((value as { items?: unknown }).items)
  )
}

export async function createPatch(payload: PatchRequest): Promise<PatchRecord> {
  const response = await fetch('/api/patches', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(`Patch creation failed (HTTP ${response.status}).`)
  }
  const data: unknown = await response.json()
  if (!isPatchRecord((data as { patch?: unknown })?.patch)) {
    throw new Error('The API returned an invalid patch response.')
  }
  return (data as { patch: PatchRecord }).patch
}

export async function listPatches(): Promise<PatchRecord[]> {
  const response = await fetch('/api/patches', {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`Patch listing failed (HTTP ${response.status}).`)
  }
  const data: unknown = await response.json()
  if (!isPatchPage(data)) {
    throw new Error('The API returned an invalid patch list response.')
  }
  return data.items.filter(isPatchRecord)
}

export async function decidePatch(
  id: string,
  decision: PatchDecision,
): Promise<PatchRecord> {
  const response = await fetch(`/api/patches/${id}/${decision.decision}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      decision: decision.decision,
      reviewer: decision.reviewer,
      reason: decision.reason,
    }),
  })
  if (!response.ok) {
    throw new Error(`Patch review failed (HTTP ${response.status}).`)
  }
  const data: unknown = await response.json()
  if (!isPatchRecord((data as { patch?: unknown })?.patch)) {
    throw new Error('The API returned an invalid review response.')
  }
  return (data as { patch: PatchRecord }).patch
}

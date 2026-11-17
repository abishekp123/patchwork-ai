import { requestJSON } from './client'

export type InvestigationStatus =
  | 'CREATED'
  | 'CONTEXT_RETRIEVAL'
  | 'INVESTIGATING'
  | 'EVIDENCE_REVIEW'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'
  | 'BUDGET_EXHAUSTED'

export interface EvidenceReference {
  evidence_id?: string
  repository_id: string
  commit_sha: string
  path: string
  start_line: number
  end_line: number
}

export interface Finding {
  statement: string
  evidence_ids: string[]
}

export interface InvestigationReport {
  summary?: string
  facts?: Finding[]
  hypotheses?: Finding[]
  next_steps?: string[]
  limitations?: string[]
  evidence?: EvidenceReference[]
  outcome?: string
  status?: InvestigationStatus
  usage?: {
    input_tokens: number
    output_tokens: number
    complete: boolean
    conservative_reserved_tokens: number
  }
  model?: string
  [key: string]: unknown
}

export interface InvestigationRecord {
  id: string
  repository_id: string
  commit_sha: string
  description: string
  status: InvestigationStatus
  created_at: string
  updated_at: string
  completed_at: string | null
  report: InvestigationReport | null
  error_code: string | null
}

export interface InvestigationStep {
  sequence: number
  created_at: string
  data: Record<string, unknown>
}

export interface ProviderStatus {
  available: boolean
  provider: string
  model: string
  reason: string | null
}

interface Page<T> {
  items: T[]
  total: number
}

export async function listInvestigations(
  repositoryId?: string,
): Promise<InvestigationRecord[]> {
  const query = repositoryId
    ? `?repository_id=${encodeURIComponent(repositoryId)}&limit=100`
    : '?limit=100'
  const page = await requestJSON<Page<InvestigationRecord>>(
    `/api/investigations${query}`,
  )
  return page.items
}

export async function getInvestigation(
  id: string,
): Promise<InvestigationRecord> {
  return requestJSON<InvestigationRecord>(`/api/investigations/${id}`)
}

export async function createInvestigation(
  repositoryId: string,
  description: string,
): Promise<InvestigationRecord> {
  const response = await requestJSON<{ investigation: InvestigationRecord }>(
    '/api/investigations',
    {
      method: 'POST',
      body: JSON.stringify({
        repository_id: repositoryId,
        description,
      }),
    },
  )
  return response.investigation
}

export async function cancelInvestigation(
  id: string,
): Promise<InvestigationRecord> {
  return requestJSON<InvestigationRecord>(`/api/investigations/${id}/cancel`, {
    method: 'POST',
  })
}

export async function listInvestigationSteps(
  id: string,
): Promise<InvestigationStep[]> {
  const page = await requestJSON<Page<InvestigationStep>>(
    `/api/investigations/${id}/steps?limit=100`,
  )
  return page.items
}

export async function getProviderStatus(): Promise<ProviderStatus> {
  return requestJSON<ProviderStatus>('/api/investigations/provider-status')
}

import { requestJSON } from './client'

export interface DashboardActivity {
  kind: 'investigation' | 'patch' | 'verification'
  id: string
  repository_id: string
  status: string
  updated_at: string
  label: string
}

export interface DashboardSummary {
  ready_repositories: number
  investigations: number
  pending_patches: number
  approved_patches: number
  active_verifications: number
  completed_verifications: number
  recent_activity: DashboardActivity[]
}

function isDashboardActivity(value: unknown): value is DashboardActivity {
  return (
    typeof value === 'object' &&
    value !== null &&
    'kind' in value &&
    ['investigation', 'patch', 'verification'].includes(String(value.kind)) &&
    'id' in value &&
    typeof value.id === 'string' &&
    'repository_id' in value &&
    typeof value.repository_id === 'string' &&
    'status' in value &&
    typeof value.status === 'string' &&
    'updated_at' in value &&
    typeof value.updated_at === 'string' &&
    'label' in value &&
    typeof value.label === 'string'
  )
}

function isDashboardSummary(value: unknown): value is DashboardSummary {
  return (
    typeof value === 'object' &&
    value !== null &&
    'ready_repositories' in value &&
    typeof value.ready_repositories === 'number' &&
    'investigations' in value &&
    typeof value.investigations === 'number' &&
    'pending_patches' in value &&
    typeof value.pending_patches === 'number' &&
    'approved_patches' in value &&
    typeof value.approved_patches === 'number' &&
    'active_verifications' in value &&
    typeof value.active_verifications === 'number' &&
    'completed_verifications' in value &&
    typeof value.completed_verifications === 'number' &&
    'recent_activity' in value &&
    Array.isArray(value.recent_activity) &&
    value.recent_activity.every(isDashboardActivity)
  )
}

export async function getDashboard(): Promise<DashboardSummary> {
  const result = await requestJSON<unknown>('/api/dashboard')
  if (!isDashboardSummary(result)) {
    throw new Error('The API returned an invalid dashboard response.')
  }
  return result
}

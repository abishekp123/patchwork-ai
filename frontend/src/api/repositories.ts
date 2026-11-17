import { requestJSON } from './client'

export interface RepositoryRecord {
  id: string
  normalized_url: string
  commit_sha: string | null
  status: 'indexing' | 'ready' | 'failed'
  created_at: string
  updated_at: string
  indexed_at: string | null
  file_count: number
  symbol_count: number
  import_count: number
}

export interface FileRecord {
  path: string
  content_hash: string
  size_bytes: number
  encoding: string
  line_count: number
  has_errors: boolean
}

export interface FileContent {
  repository_id: string
  commit_sha: string
  path: string
  content_hash: string
  start_line: number
  end_line: number
  total_lines: number
  content: string
}

export interface SearchHit {
  kind: 'symbol' | 'path' | 'text'
  path: string
  start_line: number
  end_line: number
  snippet: string
  rank: number
  name: string | null
  qualified_name: string | null
}

interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export async function listRepositories(
  signal?: AbortSignal,
): Promise<RepositoryRecord[]> {
  const page = await requestJSON<Page<RepositoryRecord>>('/api/repositories', {
    signal,
  })
  return page.items
}

export async function importRepository(url: string): Promise<RepositoryRecord> {
  const result = await requestJSON<{ repository: RepositoryRecord }>(
    '/api/repositories',
    { method: 'POST', body: JSON.stringify({ url }) },
  )
  return result.repository
}

export async function listRepositoryFiles(
  repositoryId: string,
  signal?: AbortSignal,
  offset = 0,
): Promise<FileRecord[]> {
  const page = await requestJSON<Page<FileRecord>>(
    `/api/repositories/${repositoryId}/files?limit=200&offset=${offset}`,
    { signal },
  )
  return page.items
}

export async function getRepositoryFile(
  repositoryId: string,
  path: string,
  startLine = 1,
  signal?: AbortSignal,
): Promise<FileContent> {
  const query = new URLSearchParams({ start_line: String(startLine) })
  return requestJSON<FileContent>(
    `/api/repositories/${repositoryId}/files/${encodeURIComponent(path)}/content?${query}`,
    { signal },
  )
}

export async function searchRepository(
  repositoryId: string,
  query: string,
  signal?: AbortSignal,
): Promise<SearchHit[]> {
  const params = new URLSearchParams({ q: query, limit: '50' })
  const result = await requestJSON<{ results: SearchHit[] }>(
    `/api/repositories/${repositoryId}/search?${params}`,
    { signal },
  )
  return result.results
}

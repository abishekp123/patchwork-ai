import { useEffect, useMemo, useState } from 'react'

import {
  cancelInvestigation,
  createInvestigation,
  getInvestigation,
  getProviderStatus,
  listInvestigationSteps,
  listInvestigations,
  type EvidenceReference,
  type InvestigationRecord,
  type InvestigationStatus,
  type InvestigationStep,
  type ProviderStatus,
} from '../../api/investigations'
import { createPatch, type PatchRecord } from '../../api/patches'
import { getDashboard, type DashboardSummary } from '../../api/dashboard'
import {
  getRepositoryFile,
  importRepository,
  listRepositories,
  listRepositoryFiles,
  searchRepository,
  type FileContent,
  type FileRecord,
  type RepositoryRecord,
  type SearchHit,
} from '../../api/repositories'

const terminalStatuses = new Set<InvestigationStatus>([
  'COMPLETED',
  'FAILED',
  'CANCELLED',
  'BUDGET_EXHAUSTED',
])

function shortCommit(commit: string | null): string {
  return commit ? commit.slice(0, 10) : 'not indexed'
}

function bytesLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function statusStyle(status: InvestigationStatus): string {
  if (status === 'COMPLETED') return 'bg-emerald-100 text-emerald-800'
  if (status === 'FAILED' || status === 'BUDGET_EXHAUSTED')
    return 'bg-rose-100 text-rose-800'
  if (status === 'CANCELLED') return 'bg-stone-200 text-stone-700'
  return 'bg-amber-100 text-amber-800'
}

export function DeveloperWorkspace({
  onPatchCreated,
}: {
  onPatchCreated?: () => void
}) {
  const [repositories, setRepositories] = useState<RepositoryRecord[]>([])
  const [selectedRepositoryId, setSelectedRepositoryId] = useState('')
  const [files, setFiles] = useState<FileRecord[]>([])
  const [fileOffset, setFileOffset] = useState(0)
  const [selectedPath, setSelectedPath] = useState('')
  const [sourceStart, setSourceStart] = useState(1)
  const [source, setSource] = useState<FileContent | null>(null)
  const [sourceError, setSourceError] = useState<string | null>(null)
  const [repositoryUrl, setRepositoryUrl] = useState('')
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [loadingRepositories, setLoadingRepositories] = useState(true)
  const [workspaceError, setWorkspaceError] = useState<string | null>(null)
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null)
  const [dashboardError, setDashboardError] = useState<string | null>(null)
  const [provider, setProvider] = useState<ProviderStatus | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchHit[]>([])
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [investigations, setInvestigations] = useState<InvestigationRecord[]>(
    [],
  )
  const [selectedInvestigationId, setSelectedInvestigationId] = useState('')
  const [selectedInvestigation, setSelectedInvestigation] =
    useState<InvestigationRecord | null>(null)
  const [investigationSteps, setInvestigationSteps] = useState<
    InvestigationStep[]
  >([])
  const [description, setDescription] = useState('')
  const [startingInvestigation, setStartingInvestigation] = useState(false)
  const [investigationError, setInvestigationError] = useState<string | null>(
    null,
  )
  const [creatingPatch, setCreatingPatch] = useState(false)
  const [createdPatch, setCreatedPatch] = useState<PatchRecord | null>(null)
  const [patchError, setPatchError] = useState<string | null>(null)

  const selectedRepository = repositories.find(
    (item) => item.id === selectedRepositoryId,
  )
  const currentInvestigation =
    selectedInvestigation?.id === selectedInvestigationId &&
    selectedInvestigation.repository_id === selectedRepositoryId
      ? selectedInvestigation
      : null
  const visibleInvestigations = investigations.filter(
    (item) => item.repository_id === selectedRepositoryId,
  )
  const sourceIsCurrent =
    source?.repository_id === selectedRepositoryId &&
    source.path === selectedPath &&
    source.start_line === sourceStart
  const visibleSource = sourceIsCurrent ? source : null
  const sourceLoading = Boolean(selectedPath) && !visibleSource && !sourceError
  const sourceLines = useMemo(
    () => visibleSource?.content.split('\n') ?? [],
    [visibleSource],
  )
  const evidenceById = useMemo(
    () =>
      new Map(
        (currentInvestigation?.report?.evidence ?? [])
          .filter((item): item is EvidenceReference & { evidence_id: string } =>
            Boolean(item.evidence_id),
          )
          .map((item) => [item.evidence_id, item]),
      ),
    [currentInvestigation],
  )

  useEffect(() => {
    let active = true
    async function load() {
      const [repositoryResult, providerResult] = await Promise.allSettled([
        listRepositories(),
        getProviderStatus(),
      ])
      if (!active) return
      if (repositoryResult.status === 'fulfilled') {
        setRepositories(repositoryResult.value)
        if (repositoryResult.value[0]) {
          setSelectedRepositoryId(repositoryResult.value[0].id)
        }
      } else {
        setWorkspaceError(
          repositoryResult.reason instanceof Error
            ? repositoryResult.reason.message
            : 'Could not load repositories.',
        )
      }
      if (providerResult.status === 'fulfilled') {
        setProvider(providerResult.value)
      } else {
        setProvider({
          available: false,
          provider: 'openai',
          model: '',
          reason: 'Provider status is unavailable.',
        })
      }
      setLoadingRepositories(false)
    }
    void load()
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const summary = await getDashboard()
        if (active) {
          setDashboard(summary)
          setDashboardError(null)
        }
      } catch (issue) {
        if (active) {
          setDashboardError(
            issue instanceof Error
              ? issue.message
              : 'Dashboard metrics are unavailable.',
          )
        }
      }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 10_000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    if (!selectedRepositoryId) {
      return
    }
    const controller = new AbortController()
    let active = true
    async function loadRepositoryWorkspace() {
      setWorkspaceError(null)
      const [fileResult, investigationResult] = await Promise.allSettled([
        listRepositoryFiles(
          selectedRepositoryId,
          controller.signal,
          fileOffset,
        ),
        listInvestigations(selectedRepositoryId),
      ])
      if (!active) return
      if (fileResult.status === 'fulfilled') {
        setSourceError(null)
        setFiles(fileResult.value)
        setSelectedPath((current) =>
          fileResult.value.some((item) => item.path === current)
            ? current
            : (fileResult.value[0]?.path ?? ''),
        )
      } else {
        setWorkspaceError(
          fileResult.reason instanceof Error
            ? fileResult.reason.message
            : 'Could not load indexed files.',
        )
      }
      if (investigationResult.status === 'fulfilled') {
        setInvestigations(investigationResult.value)
        setSelectedInvestigationId(
          (current) =>
            (current &&
              investigationResult.value.some((item) => item.id === current) &&
              current) ||
            investigationResult.value[0]?.id ||
            '',
        )
      } else {
        setInvestigationError(
          investigationResult.reason instanceof Error
            ? investigationResult.reason.message
            : 'Could not load investigation history.',
        )
      }
    }
    void loadRepositoryWorkspace()
    return () => {
      active = false
      controller.abort()
    }
  }, [selectedRepositoryId, fileOffset])

  useEffect(() => {
    if (!selectedRepositoryId || !selectedPath) {
      return
    }
    const controller = new AbortController()
    let active = true
    getRepositoryFile(
      selectedRepositoryId,
      selectedPath,
      sourceStart,
      controller.signal,
    )
      .then((result) => {
        if (active) setSource(result)
      })
      .catch((issue: unknown) => {
        if (active && !controller.signal.aborted) {
          setSourceError(
            issue instanceof Error ? issue.message : 'Could not load source.',
          )
        }
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [selectedRepositoryId, selectedPath, sourceStart])

  useEffect(() => {
    if (!selectedInvestigationId) {
      return
    }
    let active = true
    let refreshing = false
    const refresh = async () => {
      if (refreshing) return
      refreshing = true
      try {
        const [record, steps] = await Promise.all([
          getInvestigation(selectedInvestigationId),
          listInvestigationSteps(selectedInvestigationId),
        ])
        if (!active) return
        setSelectedInvestigation(record)
        setInvestigationSteps(steps)
        setInvestigations((current) => [
          record,
          ...current.filter((item) => item.id !== record.id),
        ])
      } catch (issue) {
        if (active) {
          setInvestigationError(
            issue instanceof Error
              ? issue.message
              : 'Could not load investigation details.',
          )
        }
      } finally {
        refreshing = false
      }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 1500)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [selectedInvestigationId])

  async function submitImport(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!repositoryUrl.trim() || importing) return
    setImporting(true)
    setImportError(null)
    try {
      const record = await importRepository(repositoryUrl.trim())
      setRepositories((current) => [
        record,
        ...current.filter((item) => item.id !== record.id),
      ])
      setSelectedRepositoryId(record.id)
      setFileOffset(0)
      setRepositoryUrl('')
    } catch (issue) {
      setImportError(
        issue instanceof Error ? issue.message : 'Repository import failed.',
      )
    } finally {
      setImporting(false)
    }
  }

  async function submitSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedRepositoryId || !searchQuery.trim() || searching) return
    setSearching(true)
    setSearchError(null)
    try {
      setSearchResults(
        await searchRepository(selectedRepositoryId, searchQuery.trim()),
      )
    } catch (issue) {
      setSearchError(issue instanceof Error ? issue.message : 'Search failed.')
    } finally {
      setSearching(false)
    }
  }

  async function submitInvestigation(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (
      !selectedRepositoryId ||
      !provider?.available ||
      !description.trim() ||
      startingInvestigation
    ) {
      return
    }
    setStartingInvestigation(true)
    setInvestigationError(null)
    try {
      const record = await createInvestigation(
        selectedRepositoryId,
        description.trim(),
      )
      setInvestigations((current) => [
        record,
        ...current.filter((item) => item.id !== record.id),
      ])
      setSelectedInvestigationId(record.id)
      setDescription('')
    } catch (issue) {
      setInvestigationError(
        issue instanceof Error
          ? issue.message
          : 'Could not start investigation.',
      )
    } finally {
      setStartingInvestigation(false)
    }
  }

  function openEvidence(reference: EvidenceReference) {
    if (
      reference.repository_id !== selectedRepositoryId ||
      reference.commit_sha !== selectedRepository?.commit_sha
    ) {
      setInvestigationError(
        'This evidence belongs to a different repository snapshot.',
      )
      return
    }
    setSourceError(null)
    setSelectedPath(reference.path)
    setSourceStart(Math.max(1, reference.start_line - 5))
  }

  function openSearchHit(hit: SearchHit) {
    setSourceError(null)
    setSelectedPath(hit.path)
    setSourceStart(Math.max(1, hit.start_line - 5))
  }

  function changeSourcePage(start: number) {
    setSourceError(null)
    setSourceStart(start)
  }

  async function stopInvestigation() {
    if (!currentInvestigation) return
    try {
      const record = await cancelInvestigation(currentInvestigation.id)
      setSelectedInvestigation(record)
      setInvestigations((current) => [
        record,
        ...current.filter((item) => item.id !== record.id),
      ])
    } catch (issue) {
      setInvestigationError(
        issue instanceof Error
          ? issue.message
          : 'Could not cancel investigation.',
      )
    }
  }

  async function submitPatch() {
    if (
      !currentInvestigation ||
      currentInvestigation.status !== 'COMPLETED' ||
      !report?.summary ||
      citedEvidenceIds.length === 0 ||
      creatingPatch
    ) {
      return
    }
    setCreatingPatch(true)
    setPatchError(null)
    try {
      const patch = await createPatch({
        repository_id: currentInvestigation.repository_id,
        investigation_id: currentInvestigation.id,
        description: report.summary,
        evidence_ids: citedEvidenceIds,
      })
      setCreatedPatch(patch)
      onPatchCreated?.()
    } catch (issue) {
      setPatchError(
        issue instanceof Error
          ? issue.message
          : 'Could not generate an evidence-backed patch.',
      )
    } finally {
      setCreatingPatch(false)
    }
  }

  const report = currentInvestigation?.report
  const citedEvidenceIds = [
    ...new Set(
      [...(report?.facts ?? []), ...(report?.hypotheses ?? [])].flatMap(
        (finding) => finding.evidence_ids,
      ),
    ),
  ].slice(0, 20)
  const activeInvestigation =
    currentInvestigation && !terminalStatuses.has(currentInvestigation.status)

  return (
    <section aria-label="Developer workspace" className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <div className="rounded-xl border border-stone-200 bg-white px-5 py-4">
          <p className="font-mono text-[11px] tracking-wider text-stone-500 uppercase">
            Indexed repositories
          </p>
          <p className="mt-2 text-2xl font-semibold tabular-nums">
            {dashboard?.ready_repositories ?? repositories.length}
          </p>
        </div>
        <div className="rounded-xl border border-stone-200 bg-white px-5 py-4">
          <p className="font-mono text-[11px] tracking-wider text-stone-500 uppercase">
            Investigations
          </p>
          <p className="mt-2 text-2xl font-semibold tabular-nums">
            {dashboard?.investigations ?? visibleInvestigations.length}
          </p>
        </div>
        <MetricCard
          label="Pending review"
          value={dashboard?.pending_patches ?? '—'}
        />
        <MetricCard
          label="Approved patches"
          value={dashboard?.approved_patches ?? '—'}
        />
        <MetricCard
          label="Active verifications"
          value={dashboard?.active_verifications ?? '—'}
        />
        <div className="rounded-xl border border-stone-200 bg-white px-5 py-4">
          <p className="font-mono text-[11px] tracking-wider text-stone-500 uppercase">
            LLM provider
          </p>
          <p className="mt-2 text-sm font-semibold">
            {provider?.available ? provider.model : 'Not configured'}
          </p>
        </div>
      </div>
      {(dashboardError || dashboard?.recent_activity.length) && (
        <details className="rounded-xl border border-stone-200 bg-white px-4 py-3">
          <summary className="cursor-pointer text-xs font-medium text-stone-700">
            Recent persisted activity
            {dashboard ? ` · ${dashboard.recent_activity.length} items` : ''}
          </summary>
          {dashboardError && (
            <p role="status" className="mt-2 text-xs text-stone-500">
              {dashboardError}
            </p>
          )}
          {dashboard && dashboard.recent_activity.length > 0 && (
            <ul className="mt-3 divide-y divide-stone-100">
              {dashboard.recent_activity.slice(0, 6).map((activity) => (
                <li
                  key={`${activity.kind}:${activity.id}`}
                  className="flex flex-wrap items-center justify-between gap-2 py-2 text-xs"
                >
                  <span className="min-w-0 truncate text-stone-700">
                    <span className="mr-2 font-mono text-[10px] uppercase text-stone-400">
                      {activity.kind}
                    </span>
                    {activity.label}
                  </span>
                  <span className="font-mono text-[10px] text-stone-500">
                    {activity.status.toLowerCase()}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </details>
      )}

      <div className="grid min-w-0 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(340px,0.82fr)]">
        <div className="min-w-0 space-y-5">
          <section className="overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-100 px-5 py-4">
              <div>
                <h2 className="text-sm font-semibold">Repository snapshot</h2>
                <p className="mt-1 text-xs text-stone-500">
                  Browse immutable indexed source by commit.
                </p>
              </div>
              <label className="sr-only" htmlFor="repository-select">
                Selected repository
              </label>
              <select
                id="repository-select"
                value={selectedRepositoryId}
                onChange={(event) => {
                  setSourceError(null)
                  setFileOffset(0)
                  setSelectedRepositoryId(event.currentTarget.value)
                }}
                disabled={!repositories.length}
                className="max-w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
              >
                {!repositories.length && (
                  <option value="">No repositories</option>
                )}
                {repositories.map((repository) => (
                  <option key={repository.id} value={repository.id}>
                    {repository.normalized_url}
                  </option>
                ))}
              </select>
            </header>
            <form
              onSubmit={(event) => void submitImport(event)}
              className="flex flex-wrap gap-2 border-b border-stone-100 bg-stone-50/80 px-5 py-4"
            >
              <label className="sr-only" htmlFor="repository-url">
                GitHub repository URL
              </label>
              <input
                id="repository-url"
                type="url"
                value={repositoryUrl}
                onChange={(event) =>
                  setRepositoryUrl(event.currentTarget.value)
                }
                placeholder="https://github.com/owner/repository"
                className="min-w-0 flex-1 rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
              />
              <button
                type="submit"
                disabled={importing || !repositoryUrl.trim()}
                className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white hover:bg-stone-700 disabled:opacity-50"
              >
                {importing ? 'Indexing…' : 'Add repository'}
              </button>
              {importError && (
                <p role="alert" className="w-full text-sm text-rose-700">
                  {importError}
                </p>
              )}
            </form>

            {selectedRepository && (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 text-xs text-stone-500">
                <span className="font-mono">
                  {shortCommit(selectedRepository.commit_sha)}
                </span>
                <span>
                  {selectedRepository.file_count} files ·{' '}
                  {selectedRepository.symbol_count} symbols
                </span>
                <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-emerald-800">
                  {selectedRepository.status}
                </span>
              </div>
            )}

            {workspaceError && (
              <p role="alert" className="px-5 py-3 text-sm text-rose-700">
                {workspaceError}
              </p>
            )}

            <div className="grid min-h-[420px] min-w-0 lg:grid-cols-[230px_minmax(0,1fr)]">
              <aside className="border-t border-stone-100 lg:border-t-0 lg:border-r">
                <div className="border-b border-stone-100 px-4 py-3">
                  <p className="text-xs font-semibold text-stone-600">Files</p>
                </div>
                <nav
                  className="max-h-[420px] overflow-auto p-2"
                  aria-label="Indexed files"
                >
                  {loadingRepositories && (
                    <p className="px-2 py-3 text-xs text-stone-500">
                      Loading repositories…
                    </p>
                  )}
                  {!loadingRepositories && files.length === 0 && (
                    <p className="px-2 py-3 text-xs text-stone-500">
                      Import a repository to browse its snapshot.
                    </p>
                  )}
                  {files.map((file) => (
                    <button
                      key={file.path}
                      type="button"
                      onClick={() => {
                        setSourceError(null)
                        setSelectedPath(file.path)
                        setSourceStart(1)
                      }}
                      aria-current={
                        selectedPath === file.path ? 'page' : undefined
                      }
                      className={`mb-0.5 block w-full truncate rounded-md px-2 py-1.5 text-left font-mono text-xs ${
                        selectedPath === file.path
                          ? 'bg-emerald-50 text-emerald-900'
                          : 'text-stone-600 hover:bg-stone-50'
                      }`}
                      title={`${file.path} · ${bytesLabel(file.size_bytes)}`}
                    >
                      {file.path}
                    </button>
                  ))}
                </nav>
                <div className="flex items-center justify-between border-t border-stone-100 px-3 py-2 text-[10px] text-stone-500">
                  <button
                    type="button"
                    aria-label="Previous file page"
                    disabled={fileOffset === 0}
                    onClick={() =>
                      setFileOffset((current) => Math.max(0, current - 200))
                    }
                    className="rounded border border-stone-300 px-2 py-1 disabled:opacity-40"
                  >
                    Previous
                  </button>
                  <span>
                    {files.length
                      ? `${fileOffset + 1}–${fileOffset + files.length} / ${selectedRepository?.file_count ?? files.length}`
                      : '0 files'}
                  </span>
                  <button
                    type="button"
                    aria-label="Next file page"
                    disabled={
                      fileOffset + files.length >=
                      (selectedRepository?.file_count ?? 0)
                    }
                    onClick={() => setFileOffset((current) => current + 200)}
                    className="rounded border border-stone-300 px-2 py-1 disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </aside>

              <div className="min-w-0 border-t border-stone-100 lg:border-t-0">
                <form
                  onSubmit={(event) => void submitSearch(event)}
                  className="flex gap-2 border-b border-stone-100 p-3"
                >
                  <label className="sr-only" htmlFor="repository-search">
                    Search code and symbols
                  </label>
                  <input
                    id="repository-search"
                    value={searchQuery}
                    onChange={(event) =>
                      setSearchQuery(event.currentTarget.value)
                    }
                    placeholder="Search code, symbols, and paths"
                    className="min-w-0 flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm"
                  />
                  <button
                    type="submit"
                    disabled={
                      searching || !searchQuery.trim() || !selectedRepositoryId
                    }
                    className="rounded-lg border border-stone-300 px-3 py-2 text-sm hover:bg-stone-50 disabled:opacity-50"
                  >
                    {searching ? 'Searching…' : 'Search'}
                  </button>
                </form>
                {searchError && (
                  <p role="alert" className="px-4 pt-3 text-sm text-rose-700">
                    {searchError}
                  </p>
                )}
                {searchResults.length > 0 && (
                  <div className="max-h-44 overflow-auto border-b border-stone-100 p-2">
                    {searchResults.map((hit, index) => (
                      <button
                        key={`${hit.path}:${hit.start_line}:${index}`}
                        type="button"
                        onClick={() => openSearchHit(hit)}
                        className="block w-full truncate rounded-md px-2 py-1.5 text-left hover:bg-stone-50"
                      >
                        <span className="font-mono text-xs text-emerald-800">
                          {hit.path}:{hit.start_line}
                        </span>
                        <span className="ml-2 text-xs text-stone-600">
                          {hit.snippet.trim()}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
                {sourceError && sourceIsCurrent === false && !sourceLoading && (
                  <p role="alert" className="px-4 py-3 text-sm text-rose-700">
                    {sourceError}
                  </p>
                )}
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-stone-100 px-4 py-3">
                  <p className="truncate font-mono text-xs text-stone-600">
                    {selectedPath || 'Select a file'}
                  </p>
                  {visibleSource && (
                    <div className="flex items-center gap-2 text-xs text-stone-500">
                      <span>
                        {visibleSource.start_line}–{visibleSource.end_line} /{' '}
                        {visibleSource.total_lines}
                      </span>
                      <button
                        type="button"
                        aria-label="Previous source lines"
                        disabled={visibleSource.start_line <= 1}
                        onClick={() =>
                          changeSourcePage(
                            Math.max(1, visibleSource.start_line - 200),
                          )
                        }
                        className="rounded border border-stone-300 px-2 py-1 disabled:opacity-40"
                      >
                        ↑
                      </button>
                      <button
                        type="button"
                        aria-label="Next source lines"
                        disabled={
                          visibleSource.end_line >= visibleSource.total_lines
                        }
                        onClick={() =>
                          changeSourcePage(visibleSource.end_line + 1)
                        }
                        className="rounded border border-stone-300 px-2 py-1 disabled:opacity-40"
                      >
                        ↓
                      </button>
                    </div>
                  )}
                </div>
                <div
                  className="max-h-[300px] min-h-48 overflow-auto bg-[#171a19] p-4 text-[12px] leading-5 text-stone-200"
                  aria-label="Indexed source code"
                  aria-busy={sourceLoading}
                >
                  {sourceLoading && (
                    <p role="status" className="text-stone-400">
                      Loading indexed source…
                    </p>
                  )}
                  {!sourceLoading && visibleSource && (
                    <pre>
                      <code>
                        {sourceLines.map((line, index) => (
                          <span
                            key={`${visibleSource.start_line + index}:${line}`}
                            className="block whitespace-pre"
                          >
                            <span className="mr-4 inline-block w-8 select-none text-right text-stone-500">
                              {visibleSource.start_line + index}
                            </span>
                            {line || ' '}
                          </span>
                        ))}
                      </code>
                    </pre>
                  )}
                  {!sourceLoading && !visibleSource && !sourceError && (
                    <p className="text-stone-400">
                      Choose a file to inspect its indexed source.
                    </p>
                  )}
                </div>
              </div>
            </div>
          </section>
        </div>

        <aside className="min-w-0 space-y-5">
          <section className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold">
                  Start an investigation
                </h2>
                <p className="mt-1 text-xs leading-5 text-stone-500">
                  The model can search and inspect this immutable commit. It
                  cannot execute repository code.
                </p>
              </div>
              <span
                className={`mt-0.5 size-2.5 shrink-0 rounded-full ${
                  provider?.available ? 'bg-emerald-500' : 'bg-stone-300'
                }`}
                aria-label={
                  provider?.available
                    ? 'Provider available'
                    : 'Provider unavailable'
                }
              />
            </div>
            {!provider?.available && (
              <p className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
                {provider?.reason ?? 'Checking provider configuration…'}
              </p>
            )}
            <form
              onSubmit={(event) => void submitInvestigation(event)}
              className="mt-4 space-y-3"
            >
              <label className="sr-only" htmlFor="investigation-description">
                Describe the bug or question
              </label>
              <textarea
                id="investigation-description"
                value={description}
                onChange={(event) => setDescription(event.currentTarget.value)}
                placeholder="Describe the bug or question to investigate…"
                rows={4}
                maxLength={8000}
                className="w-full resize-y rounded-lg border border-stone-300 px-3 py-2.5 text-sm leading-6"
              />
              <button
                type="submit"
                disabled={
                  !selectedRepositoryId ||
                  !provider?.available ||
                  !description.trim() ||
                  startingInvestigation
                }
                className="w-full rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-emerald-600 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {startingInvestigation ? 'Starting…' : 'Investigate snapshot'}
              </button>
            </form>
            {investigationError && (
              <p role="alert" className="mt-3 text-sm text-rose-700">
                {investigationError}
              </p>
            )}
          </section>

          <section className="overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm">
            <header className="flex items-center justify-between gap-3 border-b border-stone-100 px-5 py-4">
              <div>
                <h2 className="text-sm font-semibold">Investigation history</h2>
                <p className="mt-1 text-xs text-stone-500">
                  {visibleInvestigations.length} saved for this repository
                </p>
              </div>
              <label className="sr-only" htmlFor="investigation-select">
                Choose investigation
              </label>
              <select
                id="investigation-select"
                value={selectedInvestigationId}
                onChange={(event) =>
                  setSelectedInvestigationId(event.currentTarget.value)
                }
                disabled={!visibleInvestigations.length}
                className="max-w-40 rounded-lg border border-stone-300 bg-white px-2 py-1.5 text-xs"
              >
                {!visibleInvestigations.length && (
                  <option value="">No history</option>
                )}
                {visibleInvestigations.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.created_at.slice(0, 16).replace('T', ' ')} ·{' '}
                    {item.status.toLowerCase()}
                  </option>
                ))}
              </select>
            </header>
            {currentInvestigation ? (
              <div className="space-y-4 p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span
                    className={`rounded-full px-2.5 py-1 text-[10px] font-semibold tracking-wider ${statusStyle(
                      currentInvestigation.status,
                    )}`}
                  >
                    {currentInvestigation.status.replace('_', ' ')}
                  </span>
                  <span className="font-mono text-[10px] text-stone-400">
                    {investigationSteps.length} steps ·{' '}
                    {shortCommit(currentInvestigation.commit_sha)}
                  </span>
                </div>
                <p className="line-clamp-3 text-sm leading-6 text-stone-700">
                  {currentInvestigation.description}
                </p>
                {activeInvestigation && (
                  <div className="flex items-center justify-between gap-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
                    <span role="status">
                      Investigation running. Status refreshes automatically.
                    </span>
                    <button
                      type="button"
                      onClick={() => void stopInvestigation()}
                      className="font-medium underline underline-offset-2"
                    >
                      Cancel
                    </button>
                  </div>
                )}
                {currentInvestigation.error_code && (
                  <p className="rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-800">
                    {currentInvestigation.error_code === 'interrupted'
                      ? 'Interrupted by a server restart. Submit the investigation again to retry; it was not resumed automatically.'
                      : `Stopped: ${currentInvestigation.error_code}`}
                  </p>
                )}
                {report?.summary && (
                  <div>
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                      Summary
                    </h3>
                    <p className="mt-2 text-sm leading-6 text-stone-800">
                      {report.summary}
                    </p>
                  </div>
                )}
                {currentInvestigation.status === 'COMPLETED' && (
                  <div className="space-y-2 border-t border-stone-100 pt-4">
                    <button
                      type="button"
                      onClick={() => void submitPatch()}
                      disabled={
                        creatingPatch ||
                        citedEvidenceIds.length === 0 ||
                        !report?.summary
                      }
                      className="w-full rounded-lg bg-stone-900 px-3 py-2.5 text-sm font-medium text-white hover:bg-stone-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {creatingPatch
                        ? 'Generating validated patch…'
                        : 'Propose evidence-backed patch'}
                    </button>
                    {citedEvidenceIds.length === 0 && (
                      <p className="text-xs text-stone-500">
                        This report has no source-cited findings to attach to a
                        patch.
                      </p>
                    )}
                    {patchError && (
                      <p role="alert" className="text-sm text-rose-700">
                        {patchError}
                      </p>
                    )}
                    {createdPatch?.investigation_id ===
                      currentInvestigation.id && (
                      <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
                        <p className="text-sm font-medium text-emerald-900">
                          {createdPatch.title}
                        </p>
                        <p className="mt-1 text-xs text-emerald-800">
                          {createdPatch.status.replace('_', ' ')} ·{' '}
                          {createdPatch.evidence_ids.length} evidence references
                        </p>
                        <a
                          href="#patch-review"
                          className="mt-2 inline-block text-xs font-medium text-emerald-900 underline underline-offset-2"
                        >
                          Open patch review
                        </a>
                      </div>
                    )}
                  </div>
                )}
                {report?.facts?.map((finding, index) => (
                  <FindingCard
                    key={`fact-${index}`}
                    title="Observed fact"
                    finding={finding}
                    evidenceById={evidenceById}
                    onOpenEvidence={openEvidence}
                  />
                ))}
                {report?.hypotheses?.map((finding, index) => (
                  <FindingCard
                    key={`hypothesis-${index}`}
                    title="Hypothesis"
                    finding={finding}
                    evidenceById={evidenceById}
                    onOpenEvidence={openEvidence}
                  />
                ))}
                {report?.limitations && report.limitations.length > 0 && (
                  <p className="border-t border-stone-100 pt-3 text-xs leading-5 text-stone-500">
                    Limitations: {report.limitations.join(' ')}
                  </p>
                )}
                {report?.next_steps && report.next_steps.length > 0 && (
                  <div>
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                      Next steps
                    </h3>
                    <ul className="mt-2 list-inside list-disc space-y-1 text-xs leading-5 text-stone-700">
                      {report.next_steps.map((step, index) => (
                        <li key={`${index}:${step}`}>{step}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {investigationSteps.length > 0 && (
                  <details className="border-t border-stone-100 pt-3">
                    <summary className="cursor-pointer text-xs font-medium text-stone-600">
                      Recent activity ({investigationSteps.length} steps)
                    </summary>
                    <pre className="mt-2 max-h-40 overflow-auto rounded bg-stone-100 p-2 text-[10px] leading-4 text-stone-600 whitespace-pre-wrap">
                      {investigationSteps
                        .slice(-5)
                        .map(
                          (step) =>
                            `#${step.sequence} ${JSON.stringify(step.data).slice(0, 1000)}`,
                        )
                        .join('\n')}
                    </pre>
                  </details>
                )}
              </div>
            ) : (
              <p className="p-5 text-sm text-stone-500">
                Start an investigation to see progress, findings, and source
                citations here.
              </p>
            )}
          </section>
        </aside>
      </div>
    </section>
  )
}

function MetricCard({
  label,
  value,
}: {
  label: string
  value: number | string
}) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white px-5 py-4">
      <p className="font-mono text-[11px] tracking-wider text-stone-500 uppercase">
        {label}
      </p>
      <p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  )
}

function FindingCard({
  title,
  finding,
  evidenceById,
  onOpenEvidence,
}: {
  title: string
  finding: { statement: string; evidence_ids: string[] }
  evidenceById: Map<string, EvidenceReference>
  onOpenEvidence: (reference: EvidenceReference) => void
}) {
  return (
    <div className="rounded-lg border border-stone-200 bg-stone-50 p-3">
      <h3 className="text-[10px] font-semibold uppercase tracking-wider text-stone-500">
        {title}
      </h3>
      <p className="mt-1.5 text-sm leading-5 text-stone-800">
        {finding.statement}
      </p>
      {finding.evidence_ids.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {finding.evidence_ids.map((id) => {
            const reference = evidenceById.get(id)
            return reference ? (
              <button
                key={id}
                type="button"
                onClick={() => onOpenEvidence(reference)}
                className="rounded bg-emerald-100 px-2 py-1 font-mono text-[10px] text-emerald-900 hover:bg-emerald-200"
                title={`${reference.path}:${reference.start_line}`}
              >
                {reference.path}:{reference.start_line}–{reference.end_line}
              </button>
            ) : (
              <span
                key={id}
                className="rounded bg-stone-200 px-2 py-1 font-mono text-[10px] text-stone-600"
                title="Citation reference is unavailable"
              >
                {id}
              </span>
            )
          })}
        </div>
      )}
    </div>
  )
}

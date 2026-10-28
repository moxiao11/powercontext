export type SearchMode = 'hybrid' | 'keyword' | 'vector'

export interface Project {
  project_id: string
  name: string
  description?: string | null
  pc_scope_id?: string | null
  document_count?: number
  experiment_count?: number
  created_at: string
  updated_at: string
}

export interface DocumentRow {
  doc_id: string
  project_id: string
  title: string
  topic?: string | null
  file_name?: string | null
  file_type: string
  page_count: number
  char_count?: number
  chunk_count: number
  status: string
  created_at: string
}

export interface Chunk {
  chunk_id: string
  chunk_index: number
  page_no: number | null
  content: string
}

export interface Citation {
  chunk_id?: string
  doc_id?: string
  title?: string | null
  topic?: string | null
  page_no?: number | null
  location?: string
  excerpt?: string
  content?: string
  label?: string
  type?: string
  score?: number | null
  mode?: string | null
  matched_by?: string | null
  ref?: Record<string, unknown>
  id?: number
}

export interface SearchResponse {
  query: string
  mode: string
  engine: string
  sql_mode: string
  hits: Record<string, unknown>[]
  citations: Citation[]
  total: number
}

export interface Experiment {
  experiment_id: string
  project_id: string
  name: string
  objective?: string | null
  hypothesis?: string | null
  method?: string | null
  model_config?: Record<string, unknown> | null
  dataset?: string | null
  result_summary?: string | null
  metrics?: Record<string, number> | null
  issues?: string | null
  failure_reason?: string | null
  next_steps?: string | null
  status: string
  log_markdown?: string | null
  created_at: string
  updated_at: string
}

export interface MemoryEntry {
  citation?: Record<string, unknown> | null
  kind: string
  kind_label?: string
  text: string
  version?: number
  state?: string
  source_refs?: unknown[]
  score?: number
}

export interface ChatResponse {
  project_id: string
  session_id: string
  intent: string
  answer: string
  llm_used: boolean
  llm_error?: string | null
  notice?: string
  citations: Citation[]
  data_sources: { kind: string; description: string; items: Record<string, unknown>[] }[]
}

export interface HealthResponse {
  status: string
  seekdb: { connected: boolean; mode: string; version: string }
  powercontext: { url: string; reachable: boolean; ready: boolean }
  llm: { configured: boolean; model?: string | null; base_url?: string | null }
  embedding: { provider: string; dimension: number }
}

export interface SaveProgressResult {
  status?: 'saved' | 'partial'
  failed_writes?: { kind: string; text: string; error: string }[]
  scope_id: string
  session_id: string
  source: { name: string; source_id: string } | null
  source_position?: number | null
  memories: MemoryEntry[]
  handoff: Record<string, unknown>
  saved_at: string
}

export interface RestoreResult {
  scope_id: string
  project: string
  handoff: {
    status?: string
    selected_revision?: unknown
    content?: {
      objective?: string
      state?: { text?: string }[]
      disposition?: string
      next_action?: { text?: string } | null
      omissions?: { text?: string }[] | null
    } | null
    evidence_checks?: unknown[]
  } | null
  handoff_error?: string | null
  memories: MemoryEntry[]
  grouped?: Record<string, MemoryEntry[]>
  memory_error?: string | null
  prepared_context?: { status?: string; content?: string | null } | null
  answer: string
  restored_at: string
}

export interface CompareResult {
  left: { experiment_id: string; name?: string | null }
  right: { experiment_id: string; name?: string | null }
  differences: { field: string; left: unknown; right: unknown }[]
  metric_deltas: { metric: string; left: number | null; right: number | null; delta: number | null }[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    let detail = `HTTP ${response.status}`
    try {
      const body = await response.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body)
    } catch {
      /* keep status text */
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

function query(params: Record<string, string | number | boolean | undefined | null>) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  health: () => request<HealthResponse>('/api/health'),
  meta: () => request<Record<string, unknown>>('/api/meta'),

  listProjects: () => request<{ projects: Project[] }>('/api/projects'),
  createProject: (payload: { name: string; description?: string; research_profile?: string }) =>
    request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(payload) }),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  deleteProject: (id: string) =>
    request<{ deleted: boolean; retired_memories: number; memory_errors: string[] }>(
      `/api/projects/${id}`,
      { method: 'DELETE' },
    ),

  listDocuments: (projectId: string, topic?: string) =>
    request<{ documents: DocumentRow[]; topics: string[]; total: number }>(
      `/api/documents${query({ project_id: projectId, topic })}`,
    ),
  uploadDocument: (formData: FormData) =>
    request<Record<string, unknown>>('/api/documents/upload', {
      method: 'POST',
      body: formData,
      headers: {},
    }),
  documentChunks: (docId: string, projectId: string) =>
    request<{ chunks: Chunk[]; total: number }>(
      `/api/documents/${docId}/chunks${query({ project_id: projectId })}`,
    ),
  deleteDocument: (docId: string, projectId: string) =>
    request<{ deleted: boolean }>(`/api/documents/${docId}${query({ project_id: projectId })}`, {
      method: 'DELETE',
    }),
  search: (payload: { project_id: string; query: string; mode: SearchMode; limit?: number; doc_id?: string }) =>
    request<SearchResponse>('/api/search', { method: 'POST', body: JSON.stringify(payload) }),

  listExperiments: (projectId: string, filters?: { dataset?: string; status?: string }) =>
    request<{ experiments: Experiment[]; total: number }>(
      `/api/experiments${query({ project_id: projectId, ...filters })}`,
    ),
  createExperiment: (payload: Record<string, unknown>) =>
    request<Experiment>('/api/experiments', { method: 'POST', body: JSON.stringify(payload) }),
  updateExperiment: (id: string, projectId: string, payload: Record<string, unknown>) =>
    request<Experiment>(`/api/experiments/${id}${query({ project_id: projectId })}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteExperiment: (id: string, projectId: string) =>
    request<{ deleted: boolean }>(`/api/experiments/${id}${query({ project_id: projectId })}`, {
      method: 'DELETE',
    }),
  getExperiment: (id: string, projectId: string) =>
    request<Experiment>(`/api/experiments/${id}${query({ project_id: projectId })}`),
  searchExperiments: (payload: { project_id: string; query: string; limit?: number }) =>
    request<{ experiments: Experiment[]; engine: string; sql_mode: string; total: number }>(
      '/api/experiments/search',
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  compareExperiments: (projectId: string, left: string, right: string) =>
    request<CompareResult>(
      `/api/experiments/compare${query({ project_id: projectId, left, right })}`,
    ),
  bestExperiment: (projectId: string, metric: string, higherIsBetter = true) =>
    request<Record<string, unknown>>(
      `/api/experiments/best${query({ project_id: projectId, metric, higher_is_better: higherIsBetter })}`,
    ),
  importExperiments: (projectId: string, records: Record<string, unknown>[]) =>
    request<{ imported: number; experiments: Experiment[] }>(
      `/api/experiments/import${query({ project_id: projectId })}`,
      { method: 'POST', body: JSON.stringify(records) },
    ),
  experimentToMemory: (
    experimentId: string,
    payload: {
      project_id: string
      conclusion?: string
      decision?: string
      next_steps?: string
      include_failure?: boolean
    },
  ) =>
    request<{
      experiment_id: string
      scope_id: string
      written: MemoryEntry[]
      skipped: string[]
      evidence: Record<string, unknown>
    }>(`/api/experiments/${experimentId}/to-memory`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  memoryKinds: () => request<{ kinds: { kind: string; label: string }[] }>('/api/memory/kinds'),
  listMemories: (projectId: string, includeInactive = false) =>
    request<{ entries: MemoryEntry[]; grouped: Record<string, MemoryEntry[]>; total: number; scope_id: string }>(
      `/api/memory${query({ project_id: projectId, include_inactive: includeInactive })}`,
    ),
  writeMemory: (payload: {
    project_id: string
    kind: string
    text: string
    reason?: string
    evidence?: Record<string, unknown>
  }) => request<MemoryEntry>('/api/memory', { method: 'POST', body: JSON.stringify(payload) }),
  searchMemories: (payload: { project_id: string; query: string; limit?: number }) =>
    request<{ hits: MemoryEntry[]; mode?: string }>('/api/memory/search', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  reviseMemory: (payload: {
    project_id: string
    citation: Record<string, unknown>
    kind: string
    text: string
    reason?: string
  }) => request<MemoryEntry>('/api/memory/revise', { method: 'POST', body: JSON.stringify(payload) }),
  retireMemory: (payload: { project_id: string; citation: Record<string, unknown>; reason?: string }) =>
    request<Record<string, unknown>>('/api/memory/retire', { method: 'POST', body: JSON.stringify(payload) }),
  saveProgress: (payload: Record<string, unknown>) =>
    request<SaveProgressResult>('/api/memory/save-progress', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  restoreProgress: (projectId: string) =>
    request<RestoreResult>(`/api/memory/restore${query({ project_id: projectId })}`, {
      method: 'POST',
    }),
  prepareContext: (payload: { project_id: string; query: string }) =>
    request<{ scope_id: string; status: string; content: string | null }>('/api/memory/context', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  chat: (payload: { project_id: string; message: string; session_id?: string }) =>
    request<ChatResponse>('/api/chat', { method: 'POST', body: JSON.stringify(payload) }),
  clearSession: (sessionId: string) =>
    request<{ cleared: boolean }>(`/api/chat/sessions/${sessionId}`, { method: 'DELETE' }),

  generateReport: (payload: { project_id: string; start_date: string; end_date: string; title?: string }) =>
    request<{
      markdown: string
      counts: Record<string, number>
      llm_used: boolean
      memory_error?: string | null
      generated_at?: string
      data: Record<string, unknown>
    }>('/api/reports/generate', { method: 'POST', body: JSON.stringify(payload) }),
  defaultReportRange: () => request<{ start_date: string; end_date: string }>('/api/reports/default-range'),
}

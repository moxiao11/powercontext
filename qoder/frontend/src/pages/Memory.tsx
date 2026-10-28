import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Brain,
  History,
  Pencil,
  PlayCircle,
  Plus,
  Search,
  Trash2,
} from 'lucide-react'
import { api, type MemoryEntry, type RestoreResult } from '@/lib/api'
import { useApp } from '@/state/AppContext'
import { useToast } from '@/components/ui/Toast'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  Input,
  Select,
  Spinner,
  Textarea,
} from '@/components/ui/primitives'
import { Modal } from '@/components/ui/Modal'
import { Markdown } from '@/components/Markdown'
import { formatDate } from '@/lib/utils'

const KIND_ORDER = ['research_profile', 'project_context', 'decision', 'failure', 'progress', 'next_action']

const KIND_TONES: Record<string, 'neutral' | 'accent' | 'success' | 'warn' | 'danger' | 'info'> = {
  research_profile: 'info',
  project_context: 'neutral',
  decision: 'accent',
  failure: 'danger',
  progress: 'success',
  next_action: 'warn',
}

export function Memory() {
  const { currentProject, health, healthLoading } = useApp()
  const projectId = currentProject?.project_id ?? null
  const toast = useToast()

  const [includeInactive, setIncludeInactive] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [searchHits, setSearchHits] = useState<MemoryEntry[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [searchMode, setSearchMode] = useState<string | null>(null)
  const [writeOpen, setWriteOpen] = useState(false)
  const [revising, setRevising] = useState<MemoryEntry | null>(null)
  const [provenance, setProvenance] = useState<MemoryEntry | null>(null)
  const [restored, setRestored] = useState<RestoreResult | null>(null)
  const [restoring, setRestoring] = useState(false)

  const kindQuery = useQuery({
    queryKey: ['memory-kinds'],
    queryFn: api.memoryKinds,
    staleTime: 600_000,
  })
  const kinds = kindQuery.data?.kinds ?? []

  const memories = useQuery({
    queryKey: ['memories', projectId, includeInactive],
    queryFn: () => api.listMemories(projectId!, includeInactive),
    enabled: Boolean(projectId) && Boolean(health?.powercontext.ready),
  })

  const grouped = useMemo(() => {
    const source = memories.data?.grouped ?? {}
    const ordered: Record<string, MemoryEntry[]> = {}
    const known = new Set(KIND_ORDER)
    KIND_ORDER.forEach((kind) => {
      ordered[kind] = source[kind] ?? []
    })
    Object.keys(source)
      .filter((kind) => !known.has(kind))
      .forEach((kind) => {
        ordered[kind] = source[kind]
      })
    return ordered
  }, [memories.data])

  const labelOf = (kind: string) => kinds.find((item) => item.kind === kind)?.label ?? kind

  const runSearch = async () => {
    if (!projectId || !searchText.trim()) return
    setSearching(true)
    try {
      const result = await api.searchMemories({ project_id: projectId, query: searchText.trim(), limit: 20 })
      setSearchHits(result.hits)
      setSearchMode(result.mode ?? 'fts')
      if (result.hits.length === 0) {
        toast.push('PowerContext 记忆检索未命中：没有任何记忆条目的文本包含该关键词（记忆检索是全文匹配，不做语义猜测）', 'info')
      }
    } catch (error) {
      toast.push(`检索失败：${(error as Error).message}`, 'error')
      setSearchHits(null)
    } finally {
      setSearching(false)
    }
  }

  const retire = async (entry: MemoryEntry) => {
    if (!projectId || !entry.citation) {
      toast.push('该记忆缺少 citation，无法安全退役', 'error')
      return
    }
    const reason = window.prompt('退役原因（会写入 PowerContext 作为可追溯记录）', '用户手动确认该记忆已过时')
    if (reason === null) return
    try {
      await api.retireMemory({ project_id: projectId, citation: entry.citation, reason: reason.trim() || undefined })
      toast.push('记忆已退役，历史版本仍可在 PowerContext 中追溯', 'success')
      memories.refetch()
    } catch (error) {
      toast.push(`退役失败：${(error as Error).message}`, 'error')
    }
  }

  const restore = async () => {
    if (!projectId) return
    setRestoring(true)
    try {
      setRestored(await api.restoreProgress(projectId))
    } catch (error) {
      toast.push(`恢复失败：${(error as Error).message}`, 'error')
    } finally {
      setRestoring(false)
    }
  }

  if (!currentProject) {
    return <EmptyState icon={<Brain className="h-8 w-8" />} title="请先选择研究项目" description="长期记忆按 PowerContext Scope 隔离，不同项目互不可见。" />
  }

  if (healthLoading) {
    return <div className="flex items-center gap-2 text-sm text-ink-300"><Spinner className="h-4 w-4" />正在检查 PowerContext 连接…</div>
  }

  if (!health?.powercontext.ready) {
    return (
      <EmptyState
        icon={<Brain className="h-8 w-8" />}
        title="PowerContext 当前不可用"
        description={`无法读取长期记忆（${health?.powercontext.url ?? '未配置地址'}）。请启动 PowerContext 服务后重试；资料导入、seekdb 检索与实验记录不受影响。`}
      />
    )
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="长期记忆引擎"
          subtitle="存储在 PowerContext（后端为 OceanBase seekdb），按项目 Scope 隔离，支持修订与退役并保留版本历史"
          action={
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" icon={<PlayCircle className="h-3.5 w-3.5" />} loading={restoring} onClick={restore}>
                恢复研究进度
              </Button>
              <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setWriteOpen(true)}>
                新增记忆
              </Button>
            </div>
          }
        />
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[260px] flex-1">
            <Input
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void runSearch()
              }}
              placeholder="检索记忆，例如：3D 场景记忆 / 显存 / 放弃"
              aria-label="检索记忆"
            />
          </div>
          <Button variant="secondary" onClick={runSearch} loading={searching} disabled={!searchText.trim()} icon={<Search className="h-4 w-4" />}>
            检索
          </Button>
          {searchHits ? (
            <Button variant="ghost" onClick={() => { setSearchHits(null); setSearchText(''); setSearchMode(null) }}>
              返回全部记忆
            </Button>
          ) : null}
          <label className="flex items-center gap-2 text-xs text-ink-300">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={(event) => setIncludeInactive(event.target.checked)}
              className="h-3.5 w-3.5 accent-accent-500"
            />
            显示已退役记忆
          </label>
        </div>
        {searchHits ? (
          <p className="lt-muted mt-3 text-[11px]">
            命中 {searchHits.length} 条 · 检索方式 {searchMode} · PowerContext 的记忆检索是全文匹配，未命中说明没有记忆条目包含该关键词，系统不会编造内容。
          </p>
        ) : null}
        <p className="lt-muted mt-2 text-[11px]">
          Scope：<span className="font-mono">{memories.data?.scope_id ?? '—'}</span> · 共 {memories.data?.total ?? 0} 条活跃记忆
        </p>
      </Card>

      {kindQuery.isLoading ? (
        <div className="flex items-center gap-2 text-xs text-ink-400">
          <Spinner className="h-3.5 w-3.5" /> 加载记忆类型…
        </div>
      ) : null}

      {searchHits ? (
        <Card>
          <CardHeader title="记忆检索结果" subtitle="点击「溯源」可查看该记忆的 citation、版本与来源引用" />
          {searchHits.length === 0 ? (
            <EmptyState icon={<Search className="h-6 w-6" />} title="没有匹配的记忆" description="换一个关键词，或查看下方按类型分组的全部记忆。" />
          ) : (
            <div className="space-y-2">
              {searchHits.map((entry, index) => (
                <MemoryRow
                  key={index}
                  entry={entry}
                  label={entry.kind_label ?? labelOf(entry.kind)}
                  onRevise={setRevising}
                  onRetire={retire}
                  onProvenance={setProvenance}
                />
              ))}
            </div>
          )}
        </Card>
      ) : memories.isLoading ? (
        <Card>
          <div className="flex items-center gap-2 py-3 text-xs text-ink-400">
            <Spinner className="h-3.5 w-3.5" /> 正在从 PowerContext 读取记忆…
          </div>
        </Card>
      ) : memories.error ? (
        <ErrorNote>{(memories.error as Error).message}</ErrorNote>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          {Object.entries(grouped).map(([kind, entries]) => (
            <Card key={kind}>
              <CardHeader
                title={
                  <span className="flex items-center gap-2">
                    <Badge tone={KIND_TONES[kind] ?? 'neutral'}>{labelOf(kind)}</Badge>
                    <span className="lt-muted text-xs font-normal">{entries.length} 条</span>
                  </span>
                }
                subtitle={`kind = ${kind}`}
              />
              {entries.length === 0 ? (
                <p className="lt-muted text-xs leading-relaxed">暂无该类型的记忆。</p>
              ) : (
                <div className="space-y-2">
                  {entries.map((entry, index) => (
                    <MemoryRow
                      key={index}
                      entry={entry}
                      label={labelOf(kind)}
                      onRevise={setRevising}
                      onRetire={retire}
                      onProvenance={setProvenance}
                    />
                  ))}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      <WriteModal
        open={writeOpen}
        projectId={projectId}
        kinds={kinds}
        onClose={() => setWriteOpen(false)}
        onDone={() => {
          setWriteOpen(false)
          memories.refetch()
        }}
      />
      <ReviseModal
        entry={revising}
        projectId={projectId}
        kinds={kinds}
        onClose={() => setRevising(null)}
        onDone={() => {
          setRevising(null)
          memories.refetch()
          setSearchHits(null)
        }}
      />
      <ProvenanceModal entry={provenance} onClose={() => setProvenance(null)} />
      <RestoreModal result={restored} onClose={() => setRestored(null)} />
    </div>
  )
}

function MemoryRow({
  entry,
  label,
  onRevise,
  onRetire,
  onProvenance,
}: {
  entry: MemoryEntry
  label: string
  onRevise: (entry: MemoryEntry) => void
  onRetire: (entry: MemoryEntry) => void
  onProvenance: (entry: MemoryEntry) => void
}) {
  const inactive = entry.state && entry.state !== 'active'
  return (
    <div className={`rounded-lg border px-3 py-2 ${inactive ? 'border-ink-800 bg-ink-900/30 opacity-70' : 'border-ink-700/70 bg-ink-900/50'}`}>
      <p className="whitespace-pre-wrap text-xs leading-relaxed text-ink-200">{entry.text}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <Badge>{label}</Badge>
        {entry.version ? <Badge tone="info">v{entry.version}</Badge> : null}
        {inactive ? <Badge tone="warn">{entry.state}</Badge> : null}
        {typeof entry.score === 'number' ? <span className="lt-muted font-mono text-[10px]">score {entry.score.toFixed(3)}</span> : null}
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant="ghost" icon={<History className="h-3 w-3" />} onClick={() => onProvenance(entry)}>
            溯源
          </Button>
          {entry.citation ? (
            <>
              <Button size="sm" variant="ghost" icon={<Pencil className="h-3 w-3" />} onClick={() => onRevise(entry)}>
                修订
              </Button>
              <Button size="sm" variant="ghost" icon={<Trash2 className="h-3 w-3 text-rose-400" />} onClick={() => onRetire(entry)} aria-label="退役该记忆" />
            </>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function WriteModal({
  open,
  projectId,
  kinds,
  onClose,
  onDone,
}: {
  open: boolean
  projectId: string | null
  kinds: { kind: string; label: string }[]
  onClose: () => void
  onDone: () => void
}) {
  const toast = useToast()
  const [kind, setKind] = useState('decision')
  const [text, setText] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!projectId || !text.trim()) return
    setBusy(true)
    setError(null)
    try {
      await api.writeMemory({
        project_id: projectId,
        kind,
        text: text.trim(),
        reason: reason.trim() || undefined,
        evidence: { origin: 'labtrace-ui-manual', confirmed_by_user: true },
      })
      toast.push('记忆已写入 PowerContext', 'success')
      setText('')
      setReason('')
      onDone()
    } catch (err) {
      setError((err as Error).message)
      toast.push(`写入失败：${(err as Error).message}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="新增长期记忆"
      description="手动写入的记忆会标记为经用户确认，不会被当作模型猜测。"
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={onClose}>取消</Button>
          <Button loading={busy} disabled={!text.trim()} onClick={submit}>写入 PowerContext</Button>
        </>
      }
    >
      <div className="space-y-4">
        <Select label="记忆类型" value={kind} onChange={(event) => setKind(event.target.value)}>
          {kinds.map((item) => (
            <option key={item.kind} value={item.kind}>{item.label}（{item.kind}）</option>
          ))}
        </Select>
        <Textarea label="记忆内容" rows={4} value={text} onChange={(event) => setText(event.target.value)} placeholder="例如：确定采用 3D 场景记忆方案，因为长时序问答准确率高出基线 4.1 个点" />
        <Input label="修订原因（可选）" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="为什么会记录这条内容" />
        {error ? <ErrorNote>{error}</ErrorNote> : null}
      </div>
    </Modal>
  )
}

function ReviseModal({
  entry,
  projectId,
  kinds,
  onClose,
  onDone,
}: {
  entry: MemoryEntry | null
  projectId: string | null
  kinds: { kind: string; label: string }[]
  onClose: () => void
  onDone: () => void
}) {
  const toast = useToast()
  const [kind, setKind] = useState('decision')
  const [text, setText] = useState('')
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [signature, setSignature] = useState<string | null>(null)

  const key = entry ? `${entry.kind}:${entry.text}` : null
  if (key && key !== signature) {
    setSignature(key)
    setKind(entry?.kind ?? 'decision')
    setText(entry?.text ?? '')
    setReason('')
    setError(null)
  }

  const submit = async () => {
    if (!projectId || !entry?.citation || !text.trim()) return
    setBusy(true)
    setError(null)
    try {
      await api.reviseMemory({
        project_id: projectId,
        citation: entry.citation,
        kind,
        text: text.trim(),
        reason: reason.trim() || '用户更正记忆内容',
      })
      toast.push('记忆已修订，PowerContext 保留了修订前的版本', 'success')
      onDone()
    } catch (err) {
      setError((err as Error).message)
      toast.push(`修订失败：${(err as Error).message}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={Boolean(entry)}
      onClose={onClose}
      title="修订记忆"
      description="用于更正错误或过时的研究事实。修订是追加式的：旧版本不会被销毁。"
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={onClose}>取消</Button>
          <Button loading={busy} disabled={!text.trim()} onClick={submit}>提交修订</Button>
        </>
      }
    >
      <div className="space-y-4">
        {entry ? (
          <div className="rounded-lg border border-ink-700/70 bg-ink-950/50 px-3 py-2">
            <p className="lt-label mb-1">修订前</p>
            <p className="text-xs leading-relaxed text-ink-300">{entry.text}</p>
          </div>
        ) : null}
        <Select label="记忆类型" value={kind} onChange={(event) => setKind(event.target.value)}>
          {kinds.map((item) => (
            <option key={item.kind} value={item.kind}>{item.label}（{item.kind}）</option>
          ))}
        </Select>
        <Textarea label="修订后的内容" rows={4} value={text} onChange={(event) => setText(event.target.value)} />
        <Input label="修订原因" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="例如：该结论已被后续实验推翻" />
        {error ? <ErrorNote>{error}</ErrorNote> : null}
      </div>
    </Modal>
  )
}

function ProvenanceModal({ entry, onClose }: { entry: MemoryEntry | null; onClose: () => void }) {
  return (
    <Modal
      open={Boolean(entry)}
      onClose={onClose}
      title="记忆溯源"
      description="每条记忆都能追溯到写入它的来源，避免把模型猜测当成已确认的研究事实。"
      size="lg"
      footer={<Button variant="ghost" onClick={onClose}>关闭</Button>}
    >
      {entry ? (
        <div className="space-y-4">
          <div>
            <p className="lt-label mb-1">内容</p>
            <p className="whitespace-pre-wrap text-xs leading-relaxed text-ink-200">{entry.text}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone="accent">{entry.kind_label ?? entry.kind}</Badge>
            {entry.version ? <Badge tone="info">版本 v{entry.version}</Badge> : null}
            {entry.state ? <Badge tone={entry.state === 'active' ? 'success' : 'warn'}>{entry.state}</Badge> : null}
          </div>
          <div>
            <p className="lt-label mb-1.5">citation（PowerContext 记忆定位符）</p>
            <pre className="overflow-x-auto rounded-lg border border-ink-700 bg-ink-950/70 p-3 font-mono text-[11px] text-ink-200">
              {JSON.stringify(entry.citation ?? null, null, 2)}
            </pre>
          </div>
          <div>
            <p className="lt-label mb-1.5">source_refs（来源证据）</p>
            <pre className="overflow-x-auto rounded-lg border border-ink-700 bg-ink-950/70 p-3 font-mono text-[11px] text-ink-200">
              {JSON.stringify(entry.source_refs ?? [], null, 2)}
            </pre>
          </div>
        </div>
      ) : null}
    </Modal>
  )
}

function RestoreModal({ result, onClose }: { result: RestoreResult | null; onClose: () => void }) {
  const handoff = result?.handoff?.content
  return (
    <Modal
      open={Boolean(result)}
      onClose={onClose}
      title="新会话恢复的研究上下文"
      description={result ? `Scope ${result.scope_id} · 恢复于 ${formatDate(result.restored_at)} · ${result.memories.length} 条记忆` : undefined}
      size="xl"
      footer={<Button variant="ghost" onClick={onClose}>关闭</Button>}
    >
      {result ? (
        <div className="space-y-4">
          {result.handoff_error ? <ErrorNote>Handoff 读取失败：{result.handoff_error}</ErrorNote> : null}
          {handoff ? (
            <div className="rounded-lg border border-accent-500/25 bg-accent-500/5 px-3 py-2.5">
              <p className="lt-label mb-1">上次会话 Handoff 历史快照</p>
              <p className="lt-muted mb-2 text-[11px]">快照保留当时状态；研究计划以恢复的当前有效记忆为准。</p>
              {handoff.objective ? <p className="text-xs text-ink-100">{handoff.objective}</p> : null}
              {handoff.next_action?.text ? (
                <p className="mt-1.5 text-xs text-ink-200">下一步：{handoff.next_action.text}</p>
              ) : null}
              {handoff.omissions?.map((item, index) => (
                <p key={index} className="mt-1.5 text-xs text-ink-300">信息缺口：{item.text}</p>
              ))}
            </div>
          ) : null}
          <div>
            <p className="lt-label mb-2">恢复的记忆</p>
            {result.memories.length === 0 ? (
              <EmptyState title="没有可恢复的记忆" description="在 AI 科研助手页面完成一次会话后点击「保存本次研究进度」。" />
            ) : (
              <ul className="space-y-2">
                {result.memories.map((entry, index) => (
                  <li key={index} className="rounded-lg border border-ink-700/70 bg-ink-900/50 px-3 py-2">
                    <div className="mb-1 flex items-center gap-2">
                      <Badge tone={KIND_TONES[entry.kind] ?? 'neutral'}>{entry.kind_label ?? entry.kind}</Badge>
                      {entry.version ? <span className="lt-muted text-[11px]">v{entry.version}</span> : null}
                    </div>
                    <p className="text-xs leading-relaxed text-ink-200">{entry.text}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {result.prepared_context?.content ? (
            <div>
              <p className="lt-label mb-2">PreparedContext（PowerContext 组织后的上下文，可直接喂给大模型）</p>
              <div className="rounded-lg border border-ink-700/70 bg-ink-950/60 p-3">
                <Markdown content={result.prepared_context.content} className="text-xs" />
              </div>
            </div>
          ) : (
            <div>
              <p className="lt-label mb-2">PreparedContext</p>
              <p className="rounded-lg border border-ink-700/70 bg-ink-950/60 p-3 text-xs leading-relaxed text-ink-300">
                PowerContext 返回 status={result.prepared_context?.status ?? 'unavailable'}
                、内容为空。该接口依赖服务端的 extract / topic-memory 能力，未配置模型提供方时按官方约定返回空结果；
                跨会话恢复由上方的 Handoff 与记忆条目承担。
              </p>
            </div>
          )}
        </div>
      ) : null}
    </Modal>
  )
}

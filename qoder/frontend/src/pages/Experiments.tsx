import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Brain,
  FlaskConical,
  GitCompareArrows,
  Plus,
  Search,
  Trash2,
  Trophy,
  Upload,
} from 'lucide-react'
import { api, type CompareResult, type Experiment } from '@/lib/api'
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
import { formatDate, STATUS_LABELS, STATUS_STYLES, cn } from '@/lib/utils'

const STATUSES = ['planned', 'running', 'completed', 'failed', 'abandoned']

interface FormState {
  name: string
  objective: string
  hypothesis: string
  method: string
  dataset: string
  status: string
  model_config: string
  metrics: string
  result_summary: string
  issues: string
  failure_reason: string
  next_steps: string
  log_markdown: string
}

const EMPTY_FORM: FormState = {
  name: '',
  objective: '',
  hypothesis: '',
  method: '',
  dataset: '',
  status: 'planned',
  model_config: '',
  metrics: '',
  result_summary: '',
  issues: '',
  failure_reason: '',
  next_steps: '',
  log_markdown: '',
}

function toForm(exp: Experiment): FormState {
  return {
    name: exp.name ?? '',
    objective: exp.objective ?? '',
    hypothesis: exp.hypothesis ?? '',
    method: exp.method ?? '',
    dataset: exp.dataset ?? '',
    status: exp.status ?? 'planned',
    model_config: exp.model_config ? JSON.stringify(exp.model_config, null, 2) : '',
    metrics: exp.metrics ? JSON.stringify(exp.metrics, null, 2) : '',
    result_summary: exp.result_summary ?? '',
    issues: exp.issues ?? '',
    failure_reason: exp.failure_reason ?? '',
    next_steps: exp.next_steps ?? '',
    log_markdown: exp.log_markdown ?? '',
  }
}

function parseJsonField(raw: string, label: string): Record<string, unknown> | undefined {
  const text = raw.trim()
  if (!text) return undefined
  const parsed: unknown = JSON.parse(text)
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象`)
  }
  return parsed as Record<string, unknown>
}

export function Experiments() {
  const { currentProject } = useApp()
  const projectId = currentProject?.project_id ?? null
  const toast = useToast()

  const [statusFilter, setStatusFilter] = useState('')
  const [datasetFilter, setDatasetFilter] = useState('')
  const [searchText, setSearchText] = useState('')
  const [searchResult, setSearchResult] = useState<Experiment[] | null>(null)
  const [searching, setSearching] = useState(false)
  const [searchMeta, setSearchMeta] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ mode: 'create' } | { mode: 'edit'; experiment: Experiment } | null>(null)
  const [detail, setDetail] = useState<Experiment | null>(null)
  const [compareOpen, setCompareOpen] = useState(false)
  const [bestOpen, setBestOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [toMemory, setToMemory] = useState<Experiment | null>(null)

  const list = useQuery({
    queryKey: ['experiments', projectId, statusFilter, datasetFilter],
    queryFn: () =>
      api.listExperiments(projectId!, {
        status: statusFilter || undefined,
        dataset: datasetFilter || undefined,
      }),
    enabled: Boolean(projectId),
  })

  const rows = useMemo(() => list.data?.experiments ?? [], [list.data])
  const datasets = useMemo(
    () => Array.from(new Set(rows.map((row) => row.dataset).filter((value): value is string => Boolean(value)))).sort(),
    [rows],
  )

  const runSearch = async () => {
    if (!projectId || !searchText.trim()) return
    setSearching(true)
    try {
      const result = await api.searchExperiments({ project_id: projectId, query: searchText.trim(), limit: 10 })
      setSearchResult(result.experiments)
      setSearchMeta(`${result.engine} · ${result.sql_mode} · 命中 ${result.total} 条`)
    } catch (error) {
      toast.push(`检索失败：${(error as Error).message}`, 'error')
      setSearchResult(null)
    } finally {
      setSearching(false)
    }
  }

  const remove = async (experiment: Experiment) => {
    if (!projectId) return
    if (!window.confirm(`删除实验「${experiment.name}」？seekdb 中的记录会被移除（已写入 PowerContext 的记忆需要单独处理）。`)) return
    try {
      await api.deleteExperiment(experiment.experiment_id, projectId)
      toast.push(`已删除实验「${experiment.name}」`, 'success')
      list.refetch()
      setDetail(null)
    } catch (error) {
      toast.push(`删除失败：${(error as Error).message}`, 'error')
    }
  }

  if (!currentProject) {
    return <EmptyState icon={<FlaskConical className="h-8 w-8" />} title="请先选择研究项目" description="实验记录按项目隔离存储在 OceanBase seekdb 中。" />
  }

  const visible = searchResult ?? rows

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="实验历史检索"
          subtitle="使用 seekdb 全文索引检索历史记录，可回答「之前为什么放弃这个方案」这类问题"
          action={
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" icon={<Upload className="h-3.5 w-3.5" />} onClick={() => setImportOpen(true)}>
                导入 JSON 指标
              </Button>
              <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setEditing({ mode: 'create' })}>
                新建实验
              </Button>
            </div>
          }
        />
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[280px] flex-1">
            <Input
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void runSearch()
              }}
              placeholder="例如：为什么放弃 纯 2D 特征 方案 / 显存溢出 / scene graph 消融"
              aria-label="检索实验记录"
            />
          </div>
          <Button variant="secondary" onClick={runSearch} loading={searching} disabled={!searchText.trim()} icon={<Search className="h-4 w-4" />}>
            检索
          </Button>
          {searchResult ? (
            <Button variant="ghost" onClick={() => { setSearchResult(null); setSearchText(''); setSearchMeta(null) }}>
              清除检索结果
            </Button>
          ) : null}
        </div>
        {searchMeta ? <p className="lt-muted mt-3 font-mono text-[11px]">{searchMeta}</p> : null}
      </Card>

      <Card>
        <CardHeader
          title={searchResult ? `检索命中（${visible.length}）` : `全部实验记录（${rows.length}）`}
          subtitle="结论、决策与后续计划可写入 PowerContext，成为跨会话的长期记忆"
          action={
            <div className="flex flex-wrap items-end gap-2">
              <Select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="w-32" aria-label="按状态筛选">
                <option value="">全部状态</option>
                {STATUSES.map((status) => (
                  <option key={status} value={status}>{STATUS_LABELS[status] ?? status}</option>
                ))}
              </Select>
              <Select value={datasetFilter} onChange={(event) => setDatasetFilter(event.target.value)} className="w-40" aria-label="按数据集筛选">
                <option value="">全部数据集</option>
                {datasets.map((dataset) => (
                  <option key={dataset} value={dataset}>{dataset}</option>
                ))}
              </Select>
              <Button size="sm" variant="ghost" icon={<GitCompareArrows className="h-3.5 w-3.5" />} onClick={() => setCompareOpen(true)}>
                对比
              </Button>
              <Button size="sm" variant="ghost" icon={<Trophy className="h-3.5 w-3.5" />} onClick={() => setBestOpen(true)}>
                最优实验
              </Button>
            </div>
          }
        />
        {list.isLoading ? (
          <div className="flex items-center gap-2 py-3 text-xs text-ink-400">
            <Spinner className="h-3.5 w-3.5" /> 正在从 seekdb 读取…
          </div>
        ) : list.error ? (
          <ErrorNote>{(list.error as Error).message}</ErrorNote>
        ) : visible.length === 0 ? (
          <EmptyState
            icon={<FlaskConical className="h-6 w-6" />}
            title={searchResult ? '没有匹配的实验记录' : '还没有实验记录'}
            description={searchResult ? '换个说法再试，或检查是否记录了失败原因与结论。' : '记录目标、假设、方法、指标、问题、失败原因与下一步，AI 助手与周报都会读取这些真实记录。'}
            action={searchResult ? undefined : <Button size="sm" variant="secondary" onClick={() => setEditing({ mode: 'create' })}>新建第一组实验</Button>}
          />
        ) : (
          <div className="space-y-2">
            {visible.map((exp) => (
              <div key={exp.experiment_id} className="rounded-lg border border-ink-700/70 bg-ink-900/50 px-3 py-2.5 transition hover:border-ink-600">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <button className="min-w-0 text-left" onClick={() => setDetail(exp)}>
                    <p className="truncate text-xs font-medium text-ink-100 hover:text-accent-300">{exp.name}</p>
                    <p className="lt-muted mt-0.5 text-[11px]">
                      {exp.dataset ? `${exp.dataset} · ` : ''}
                      {exp.metrics && Object.keys(exp.metrics).length
                        ? Object.entries(exp.metrics).map(([key, value]) => `${key}=${value}`).join(' · ')
                        : '暂无指标'}
                      {' · '}
                      {formatDate(exp.created_at)}
                    </p>
                  </button>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <span className={cn('rounded-md px-2 py-0.5 text-[11px]', STATUS_STYLES[exp.status] ?? STATUS_STYLES.planned)}>
                      {STATUS_LABELS[exp.status] ?? exp.status}
                    </span>
                    <Button size="sm" variant="ghost" icon={<Brain className="h-3.5 w-3.5 text-accent-300" />} onClick={() => setToMemory(exp)}>
                      写入记忆
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing({ mode: 'edit', experiment: exp })}>
                      编辑
                    </Button>
                    <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5 text-rose-400" />} onClick={() => remove(exp)} aria-label={`删除 ${exp.name}`} />
                  </div>
                </div>
                {exp.result_summary ? <p className="lt-muted mt-1.5 line-clamp-2 text-[11px] leading-relaxed">{exp.result_summary}</p> : null}
                {exp.failure_reason ? (
                  <p className="mt-1.5 text-[11px] leading-relaxed text-rose-300/90">失败原因：{exp.failure_reason}</p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </Card>

      <ExperimentFormModal
        projectId={projectId}
        target={editing}
        onClose={() => setEditing(null)}
        onSaved={(saved) => {
          setEditing(null)
          list.refetch()
          setDetail(saved)
        }}
      />
      <DetailModal experiment={detail} onClose={() => setDetail(null)} onEdit={(exp) => { setDetail(null); setEditing({ mode: 'edit', experiment: exp }) }} />
      <CompareModal projectId={projectId} open={compareOpen} experiments={rows} onClose={() => setCompareOpen(false)} />
      <BestModal projectId={projectId} open={bestOpen} experiments={rows} onClose={() => setBestOpen(false)} />
      <ImportModal projectId={projectId} open={importOpen} onClose={() => setImportOpen(false)} onDone={() => { setImportOpen(false); list.refetch() }} />
      <ToMemoryModal projectId={projectId} experiment={toMemory} onClose={() => setToMemory(null)} />
    </div>
  )
}

function ExperimentFormModal({
  projectId,
  target,
  onClose,
  onSaved,
}: {
  projectId: string | null
  target: { mode: 'create' } | { mode: 'edit'; experiment: Experiment } | null
  onClose: () => void
  onSaved: (experiment: Experiment) => void
}) {
  const toast = useToast()
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [signature, setSignature] = useState<string | null>(null)

  const key = target ? `${target.mode}:${target.mode === 'edit' ? target.experiment.experiment_id : ''}` : null
  if (key && key !== signature) {
    setSignature(key)
    setForm(target?.mode === 'edit' ? toForm(target.experiment) : EMPTY_FORM)
    setError(null)
  }

  const set = (field: keyof FormState) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm((current) => ({ ...current, [field]: event.target.value }))

  const submit = async () => {
    if (!projectId || !target) return
    setBusy(true)
    setError(null)
    let payload: Record<string, unknown>
    try {
      payload = {
        name: form.name.trim(),
        objective: form.objective.trim() || null,
        hypothesis: form.hypothesis.trim() || null,
        method: form.method.trim() || null,
        dataset: form.dataset.trim() || null,
        status: form.status,
        model_config: parseJsonField(form.model_config, '模型配置'),
        metrics: parseJsonField(form.metrics, '指标') as Record<string, number> | undefined,
        result_summary: form.result_summary.trim() || null,
        issues: form.issues.trim() || null,
        failure_reason: form.failure_reason.trim() || null,
        next_steps: form.next_steps.trim() || null,
        log_markdown: form.log_markdown || null,
      }
    } catch (parseError) {
      setError((parseError as Error).message)
      setBusy(false)
      return
    }
    try {
      const saved =
        target.mode === 'create'
          ? await api.createExperiment({ project_id: projectId, ...payload })
          : await api.updateExperiment(target.experiment.experiment_id, projectId, payload)
      toast.push(target.mode === 'create' ? `实验「${saved.name}」已写入 seekdb` : `实验「${saved.name}」已更新`, 'success')
      onSaved(saved)
    } catch (submitError) {
      setError((submitError as Error).message)
      toast.push(`保存失败：${(submitError as Error).message}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={Boolean(target)}
      onClose={onClose}
      title={target?.mode === 'edit' ? '编辑实验记录' : '新建实验记录'}
      description="全部字段写入 OceanBase seekdb；指标与模型配置需为合法 JSON 对象。"
      size="xl"
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={onClose}>取消</Button>
          <Button loading={busy} disabled={!form.name.trim()} onClick={submit}>保存到 seekdb</Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="实验名称 *" value={form.name} onChange={set('name')} placeholder="例如：EQAv2-3DMem 场景图记忆消融" />
          <Select label="状态" value={form.status} onChange={set('status')}>
            {STATUSES.map((status) => (
              <option key={status} value={status}>{STATUS_LABELS[status] ?? status}</option>
            ))}
          </Select>
        </div>
        <Textarea label="实验目标" rows={2} value={form.objective} onChange={set('objective')} placeholder="这组实验想验证什么" />
        <Textarea label="假设" rows={2} value={form.hypothesis} onChange={set('hypothesis')} placeholder="预期的因果关系，例如：引入 3D 场景记忆可将长时序问答准确率提升 3 个点以上" />
        <Textarea label="方法与流程" rows={3} value={form.method} onChange={set('method')} placeholder="数据、模型、训练与评测流程" />
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="数据集" value={form.dataset} onChange={set('dataset')} placeholder="例如：EQA-v2 / ScanQA（示例数据）" />
          <Input label="指标（JSON 对象）" value={form.metrics} onChange={set('metrics')} placeholder='{"accuracy": 0.612, "latency_ms": 180}' />
        </div>
        <Textarea label="模型配置（JSON 对象）" rows={3} value={form.model_config} onChange={set('model_config')} className="font-mono text-xs" placeholder='{"backbone": "siglip", "memory_slots": 512}' />
        <Textarea label="结果摘要" rows={3} value={form.result_summary} onChange={set('result_summary')} placeholder="客观描述观察到的结果，不要写推测" />
        <div className="grid gap-4 sm:grid-cols-2">
          <Textarea label="遇到的问题" rows={3} value={form.issues} onChange={set('issues')} placeholder="训练不稳定、显存溢出、数据加载瓶颈…" />
          <Textarea label="失败 / 放弃原因" rows={3} value={form.failure_reason} onChange={set('failure_reason')} placeholder="若状态为失败或已放弃，请写明原因，AI 助手会用它回答「之前为什么放弃」" />
        </div>
        <Textarea label="下一步计划" rows={2} value={form.next_steps} onChange={set('next_steps')} placeholder="多条计划用换行或分号分隔，写入记忆时会拆分为独立的 next_action" />
        <Textarea label="实验日志（Markdown）" rows={6} value={form.log_markdown} onChange={set('log_markdown')} className="font-mono text-xs" placeholder="## 2026-10-20&#10;- 启动训练，lr=2e-4" />
        {error ? <ErrorNote>{error}</ErrorNote> : null}
      </div>
    </Modal>
  )
}

function DetailModal({
  experiment,
  onClose,
  onEdit,
}: {
  experiment: Experiment | null
  onClose: () => void
  onEdit: (experiment: Experiment) => void
}) {
  return (
    <Modal
      open={Boolean(experiment)}
      onClose={onClose}
      title={experiment?.name ?? ''}
      description={experiment ? `${experiment.experiment_id} · 创建于 ${formatDate(experiment.created_at)} · 更新于 ${formatDate(experiment.updated_at)}` : undefined}
      size="xl"
      footer={<Button variant="secondary" onClick={() => experiment && onEdit(experiment)}>编辑</Button>}
    >
      {experiment ? (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Badge tone="accent">{STATUS_LABELS[experiment.status] ?? experiment.status}</Badge>
            {experiment.dataset ? <Badge tone="info">{experiment.dataset}</Badge> : null}
            {experiment.metrics
              ? Object.entries(experiment.metrics).map(([key, value]) => (
                  <Badge key={key}>
                    {key} = {value}
                  </Badge>
                ))
              : null}
          </div>
          <Field label="实验目标" value={experiment.objective} />
          <Field label="假设" value={experiment.hypothesis} />
          <Field label="方法与流程" value={experiment.method} />
          <Field label="结果摘要" value={experiment.result_summary} />
          <Field label="遇到的问题" value={experiment.issues} />
          <Field label="失败 / 放弃原因" value={experiment.failure_reason} tone="danger" />
          <Field label="下一步计划" value={experiment.next_steps} />
          {experiment.model_config ? (
            <div>
              <p className="lt-label mb-1.5">模型配置</p>
              <pre className="overflow-x-auto rounded-lg border border-ink-700 bg-ink-950/70 p-3 font-mono text-xs text-ink-200">
                {JSON.stringify(experiment.model_config, null, 2)}
              </pre>
            </div>
          ) : null}
          {experiment.log_markdown ? (
            <div>
              <p className="lt-label mb-1.5">实验日志</p>
              <div className="rounded-lg border border-ink-700 bg-ink-950/50 p-3">
                <Markdown content={experiment.log_markdown} className="text-xs" />
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </Modal>
  )
}

function Field({ label, value, tone }: { label: string; value?: string | null; tone?: 'danger' }) {
  if (!value) return null
  return (
    <div>
      <p className="lt-label mb-1">{label}</p>
      <p className={cn('whitespace-pre-wrap text-xs leading-relaxed', tone === 'danger' ? 'text-rose-300/90' : 'text-ink-200')}>{value}</p>
    </div>
  )
}

function CompareModal({
  projectId,
  open,
  experiments,
  onClose,
}: {
  projectId: string | null
  open: boolean
  experiments: Experiment[]
  onClose: () => void
}) {
  const [left, setLeft] = useState('')
  const [right, setRight] = useState('')
  const [result, setResult] = useState<CompareResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    if (!projectId || !left || !right) return
    setBusy(true)
    setError(null)
    try {
      setResult(await api.compareExperiments(projectId, left, right))
    } catch (err) {
      setError((err as Error).message)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onClose={() => { setResult(null); setError(null); onClose() }} title="实验对比" description="逐字段对比两组实验记录，并计算指标差值" size="lg" footer={<Button variant="ghost" onClick={() => { setResult(null); setError(null); onClose() }}>关闭</Button>}>
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Select label="实验 A" value={left} onChange={(event) => setLeft(event.target.value)}>
            <option value="">请选择</option>
            {experiments.map((exp) => (
              <option key={exp.experiment_id} value={exp.experiment_id}>{exp.name}</option>
            ))}
          </Select>
          <Select label="实验 B" value={right} onChange={(event) => setRight(event.target.value)}>
            <option value="">请选择</option>
            {experiments.map((exp) => (
              <option key={exp.experiment_id} value={exp.experiment_id}>{exp.name}</option>
            ))}
          </Select>
        </div>
        <Button onClick={run} loading={busy} disabled={!left || !right || left === right}>对比</Button>
        {error ? <ErrorNote>{error}</ErrorNote> : null}
        {result ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-ink-700/70 bg-ink-900/50 px-3 py-2">
                <p className="lt-label">实验 A</p>
                <p className="text-xs text-ink-100">{result.left.name ?? result.left.experiment_id}</p>
              </div>
              <div className="rounded-lg border border-ink-700/70 bg-ink-900/50 px-3 py-2">
                <p className="lt-label">实验 B</p>
                <p className="text-xs text-ink-100">{result.right.name ?? result.right.experiment_id}</p>
              </div>
            </div>

            <div>
              <p className="lt-label mb-1.5">指标差值</p>
              {result.metric_deltas.length === 0 ? (
                <p className="lt-muted text-xs">两组实验都没有记录指标。</p>
              ) : (
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="lt-label border-b border-ink-700/70">
                      <th className="py-1.5 pr-3 font-medium">指标</th>
                      <th className="py-1.5 pr-3 font-medium">A</th>
                      <th className="py-1.5 pr-3 font-medium">B</th>
                      <th className="py-1.5 font-medium">差值</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-800/70">
                    {result.metric_deltas.map((row) => (
                      <tr key={row.metric}>
                        <td className="py-1.5 pr-3 font-mono text-ink-200">{row.metric}</td>
                        <td className="py-1.5 pr-3 text-ink-300">{row.left ?? '—'}</td>
                        <td className="py-1.5 pr-3 text-ink-300">{row.right ?? '—'}</td>
                        <td className={cn('py-1.5 font-mono', row.delta === null ? 'text-ink-500' : row.delta > 0 ? 'text-emerald-300' : row.delta < 0 ? 'text-rose-300' : 'text-ink-300')}>
                          {row.delta === null ? '—' : row.delta > 0 ? `+${row.delta}` : row.delta}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div>
              <p className="lt-label mb-1.5">字段差异（{result.differences.length}）</p>
              {result.differences.length === 0 ? (
                <p className="lt-muted text-xs">两组实验的字段完全一致。</p>
              ) : (
                <ul className="space-y-1.5">
                  {result.differences.map((diff) => (
                    <li key={diff.field} className="rounded-lg border border-ink-700/70 bg-ink-900/50 px-3 py-2">
                      <p className="lt-label mb-1 font-mono text-[10px]">{diff.field}</p>
                      <p className="text-[11px] leading-relaxed text-rose-300/80">A：{renderValue(diff.left)}</p>
                      <p className="text-[11px] leading-relaxed text-emerald-300/80">B：{renderValue(diff.right)}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </Modal>
  )
}

function renderValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '（空）'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function BestModal({
  projectId,
  open,
  experiments,
  onClose,
}: {
  projectId: string | null
  open: boolean
  experiments: Experiment[]
  onClose: () => void
}) {
  const metricNames = useMemo(
    () => Array.from(new Set(experiments.flatMap((exp) => Object.keys(exp.metrics ?? {})))).sort(),
    [experiments],
  )
  const [metric, setMetric] = useState('')
  const [higher, setHigher] = useState(true)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    if (!projectId || !metric) return
    setBusy(true)
    setError(null)
    try {
      setResult(await api.bestExperiment(projectId, metric, higher))
    } catch (err) {
      setError((err as Error).message)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  const best = result?.best as Experiment | null | undefined

  return (
    <Modal open={open} onClose={() => { setResult(null); setError(null); onClose() }} title="按指标查找最优实验" description="直接扫描 seekdb 中的真实指标记录，不会虚构数值" size="lg" footer={<Button variant="ghost" onClick={() => { setResult(null); setError(null); onClose() }}>关闭</Button>}>
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Select label="指标" value={metric} onChange={(event) => setMetric(event.target.value)}>
            <option value="">请选择</option>
            {metricNames.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </Select>
          <Select label="方向" value={higher ? 'higher' : 'lower'} onChange={(event) => setHigher(event.target.value === 'higher')}>
            <option value="higher">越大越好</option>
            <option value="lower">越小越好</option>
          </Select>
        </div>
        <Button onClick={run} loading={busy} disabled={!metric}>查找</Button>
        {error ? <ErrorNote>{error}</ErrorNote> : null}
        {result ? (
          best ? (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2.5">
              <p className="text-xs font-medium text-emerald-200">{best.name}</p>
              <p className="lt-muted mt-1 text-[11px]">
                {metric} = {best.metrics?.[metric]} · {STATUS_LABELS[best.status] ?? best.status} · {formatDate(best.created_at)}
              </p>
            </div>
          ) : (
            <p className="lt-muted text-xs">{String(result.note ?? '没有找到记录了该指标的实验。')}</p>
          )
        ) : null}
      </div>
    </Modal>
  )
}

const IMPORT_TEMPLATE = `[
  {
    "name": "示例实验 A（示例数据，非真实科研结果）",
    "dataset": "EQA-v2-sample",
    "status": "completed",
    "metrics": { "accuracy": 0.58 },
    "result_summary": "示例：基线在长时序问题上准确率偏低。",
    "next_steps": "示例：引入场景记忆模块后复测"
  }
]`

function ImportModal({
  projectId,
  open,
  onClose,
  onDone,
}: {
  projectId: string | null
  open: boolean
  onClose: () => void
  onDone: () => void
}) {
  const toast = useToast()
  const [raw, setRaw] = useState(IMPORT_TEMPLATE)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!projectId) return
    setBusy(true)
    setError(null)
    let records: unknown
    try {
      records = JSON.parse(raw)
    } catch (parseError) {
      setError(`JSON 解析失败：${(parseError as Error).message}`)
      setBusy(false)
      return
    }
    if (!Array.isArray(records)) {
      setError('顶层必须是实验对象数组')
      setBusy(false)
      return
    }
    try {
      const result = await api.importExperiments(projectId, records as Record<string, unknown>[])
      toast.push(`已导入 ${result.imported} 组实验到 seekdb`, 'success')
      onDone()
    } catch (err) {
      setError((err as Error).message)
      toast.push(`导入失败：${(err as Error).message}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="批量导入实验指标（JSON）"
      description="用于把已有训练脚本产出的 metrics.json 直接落库。示例内容仅为格式演示，不是真实科研结果。"
      size="lg"
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={onClose}>取消</Button>
          <Button loading={busy} onClick={submit}>导入</Button>
        </>
      }
    >
      <div className="space-y-3">
        <Textarea rows={14} value={raw} onChange={(event) => setRaw(event.target.value)} className="font-mono text-xs" aria-label="实验 JSON" />
        {error ? <ErrorNote>{error}</ErrorNote> : null}
      </div>
    </Modal>
  )
}

function ToMemoryModal({
  projectId,
  experiment,
  onClose,
}: {
  projectId: string | null
  experiment: Experiment | null
  onClose: () => void
}) {
  const toast = useToast()
  const [conclusion, setConclusion] = useState('')
  const [decision, setDecision] = useState('')
  const [nextSteps, setNextSteps] = useState('')
  const [includeFailure, setIncludeFailure] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<{ written: string[]; skipped: string[] } | null>(null)

  const submit = async () => {
    if (!projectId || !experiment) return
    setBusy(true)
    setError(null)
    setDone(null)
    try {
      const result = await api.experimentToMemory(experiment.experiment_id, {
        project_id: projectId,
        conclusion: conclusion.trim() || undefined,
        decision: decision.trim() || undefined,
        next_steps: nextSteps.trim() || experiment.next_steps || undefined,
        include_failure: includeFailure,
      })
      setDone({
        written: result.written.map((entry) => `${entry.kind_label ?? entry.kind}：${entry.text}`),
        skipped: result.skipped,
      })
      toast.push(`已写入 ${result.written.length} 条 PowerContext 记忆（携带实验溯源标识）`, 'success')
    } catch (err) {
      setError((err as Error).message)
      toast.push(`写入失败：${(err as Error).message}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={Boolean(experiment)}
      onClose={() => { setDone(null); setError(null); setConclusion(''); setDecision(''); setNextSteps(''); onClose() }}
      title="写入 PowerContext 长期记忆"
      description={experiment ? `把「${experiment.name}」的结论沉淀为跨会话记忆，每条记忆都带有指向该实验记录的溯源标识。` : undefined}
      size="lg"
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={onClose}>关闭</Button>
          <Button loading={busy} onClick={submit} disabled={Boolean(done)}>写入记忆</Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="lt-muted text-xs leading-relaxed">
          默认只搬运实验记录中已有的文本（结果摘要、失败原因、下一步计划）。下面两个字段留空时不会写入任何内容——系统不会把模型猜测当作已确认的研究事实。
        </p>
        <Textarea label="补充结论（可选）" rows={2} value={conclusion} onChange={(event) => setConclusion(event.target.value)} placeholder="留空则使用实验记录中的结果摘要" />
        <Textarea label="研究决策（可选）" rows={2} value={decision} onChange={(event) => setDecision(event.target.value)} placeholder="例如：确定采用 3D 场景记忆而非纯 2D 特征，因为长时序问答准确率更高" />
        <Textarea label="下一步计划" rows={2} value={nextSteps} onChange={(event) => setNextSteps(event.target.value)} placeholder={experiment?.next_steps ?? '留空则使用实验记录中的下一步计划'} />
        <label className="flex items-center gap-2 text-xs text-ink-300">
          <input type="checkbox" checked={includeFailure} onChange={(event) => setIncludeFailure(event.target.checked)} className="h-3.5 w-3.5 accent-accent-500" />
          当状态为失败 / 已放弃且记录了原因时，同时写入 failure 记忆
        </label>
        {error ? <ErrorNote>{error}</ErrorNote> : null}
        {done ? (
          <div className="space-y-2">
            <p className="lt-label">已写入 {done.written.length} 条</p>
            {done.written.map((line, index) => (
              <p key={index} className="rounded-lg border border-emerald-500/25 bg-emerald-500/5 px-3 py-2 text-xs leading-relaxed text-emerald-100/90">
                {line}
              </p>
            ))}
            {done.skipped.length ? (
              <p className="lt-muted text-[11px]">跳过：{done.skipped.join('、')}</p>
            ) : null}
          </div>
        ) : null}
      </div>
    </Modal>
  )
}

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  Activity,
  BookOpen,
  Brain,
  ChevronRight,
  FlaskConical,
  ListChecks,
  PlayCircle,
} from 'lucide-react'
import { api, type RestoreResult } from '@/lib/api'
import { useApp } from '@/state/AppContext'
import { useToast } from '@/components/ui/Toast'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorNote, Spinner } from '@/components/ui/primitives'
import { Modal } from '@/components/ui/Modal'
import { Markdown } from '@/components/Markdown'
import { formatDate, STATUS_LABELS, STATUS_STYLES, cn, truncate } from '@/lib/utils'

const KIND_LABELS: Record<string, string> = {
  research_profile: '研究方向',
  project_context: '项目背景',
  decision: '研究决策',
  failure: '失败记录',
  progress: '进展',
  next_action: '下一步',
}

export function Overview() {
  const { currentProject, projects, projectsLoading, health } = useApp()
  const projectId = currentProject?.project_id ?? null
  const toast = useToast()
  const [restored, setRestored] = useState<RestoreResult | null>(null)
  const [restoring, setRestoring] = useState(false)

  const documents = useQuery({
    queryKey: ['documents', projectId],
    queryFn: () => api.listDocuments(projectId!),
    enabled: Boolean(projectId),
  })
  const experiments = useQuery({
    queryKey: ['experiments', projectId],
    queryFn: () => api.listExperiments(projectId!),
    enabled: Boolean(projectId),
  })
  const memories = useQuery({
    queryKey: ['memories', projectId],
    queryFn: () => api.listMemories(projectId!),
    enabled: Boolean(projectId),
  })

  const restore = async () => {
    if (!projectId) return
    setRestoring(true)
    try {
      const result = await api.restoreProgress(projectId)
      setRestored(result)
      toast.push('已从 PowerContext 恢复该项目的研究上下文', 'success')
    } catch (error) {
      toast.push(`恢复失败：${(error as Error).message}`, 'error')
    } finally {
      setRestoring(false)
    }
  }

  if (projectsLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-ink-400">
        <Spinner className="h-3.5 w-3.5" /> 正在加载研究项目…
      </div>
    )
  }

  if (!currentProject) {
    return (
      <EmptyState
        icon={<Activity className="h-8 w-8" />}
        title="还没有研究项目"
        description="LabTrace 按项目隔离全部科研数据：每个项目拥有独立的 seekdb 数据分区与 PowerContext Scope，长期记忆互不干扰。请在左侧「新建研究项目」开始。"
      />
    )
  }

  const recentDocs = (documents.data?.documents ?? []).slice(0, 5)
  const recentExperiments = (experiments.data?.experiments ?? []).slice(0, 5)
  const grouped = memories.data?.grouped ?? {}
  const nextActions = grouped.next_action ?? []
  const decisions = grouped.decision ?? []
  const failures = grouped.failure ?? []
  const memoryTotal = memories.data?.total ?? 0

  return (
    <div className="space-y-5">
      <Card className="relative overflow-hidden">
        <div className="pointer-events-none absolute -right-16 -top-20 h-52 w-52 rounded-full bg-accent-500/10 blur-3xl" />
        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="lt-label">当前研究项目</p>
            <h2 className="mt-1 truncate text-xl font-semibold tracking-tight text-ink-50">{currentProject.name}</h2>
            {currentProject.description ? (
              <p className="lt-muted mt-2 max-w-2xl text-xs leading-relaxed">{currentProject.description}</p>
            ) : null}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Badge tone="info">
                <BookOpen className="h-3 w-3" /> {documents.data?.total ?? currentProject.document_count ?? 0} 篇资料
              </Badge>
              <Badge tone="accent">
                <FlaskConical className="h-3 w-3" /> {experiments.data?.total ?? currentProject.experiment_count ?? 0} 组实验
              </Badge>
              <Badge tone={memoryTotal ? 'success' : 'neutral'}>
                <Brain className="h-3 w-3" /> {memoryTotal} 条长期记忆
              </Badge>
              {currentProject.pc_scope_id ? (
                <Badge tone="success">Scope {currentProject.pc_scope_id}</Badge>
              ) : (
                <Badge tone="danger">未绑定 PowerContext Scope</Badge>
              )}
            </div>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-2">
            <Button icon={<PlayCircle className="h-4 w-4" />} loading={restoring} onClick={restore}>
              继续上次研究
            </Button>
            <span className="lt-muted text-[11px]">
              从 PowerContext 读取已保存的进度、决策与下一步
            </span>
          </div>
        </div>
      </Card>

      {!health?.powercontext.ready ? (
        <ErrorNote>
          PowerContext 当前不可用（{health?.powercontext.url ?? '未连接'}）。长期记忆、进度接续与周报的结论部分会降级；资料导入、seekdb
          检索与实验记录等非生成式功能仍可正常使用。
        </ErrorNote>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="最近上传的资料"
            subtitle="分块与向量索引存储在 OceanBase seekdb"
            action={
              <Link to="/library" className="flex items-center gap-1 text-xs text-accent-300 transition hover:text-accent-400">
                知识库 <ChevronRight className="h-3 w-3" />
              </Link>
            }
          />
          {documents.isLoading ? (
            <LoadingRow />
          ) : documents.error ? (
            <ErrorNote>{(documents.error as Error).message}</ErrorNote>
          ) : recentDocs.length === 0 ? (
            <EmptyState
              icon={<BookOpen className="h-6 w-6" />}
              title="还没有导入论文或笔记"
              description="支持 PDF / Markdown / TXT，上传后会按段落切块、保留页码并写入 seekdb 全文索引与向量索引。"
              action={
                <Link to="/library">
                  <Button size="sm" variant="secondary">前往知识库</Button>
                </Link>
              }
            />
          ) : (
            <ul className="divide-y divide-ink-800/70">
              {recentDocs.map((doc) => (
                <li key={doc.doc_id} className="flex items-start justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate text-xs font-medium text-ink-100">{doc.title}</p>
                    <p className="lt-muted mt-0.5 text-[11px]">
                      {doc.file_type.toUpperCase()} · {doc.chunk_count} 个分块
                      {doc.page_count ? ` · ${doc.page_count} 页` : ''} · {formatDate(doc.created_at)}
                    </p>
                  </div>
                  {doc.topic ? <Badge>{truncate(doc.topic, 12)}</Badge> : null}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader
            title="最近的实验记录"
            subtitle="结论与失败原因可一键写入 PowerContext"
            action={
              <Link to="/experiments" className="flex items-center gap-1 text-xs text-accent-300 transition hover:text-accent-400">
                实验中心 <ChevronRight className="h-3 w-3" />
              </Link>
            }
          />
          {experiments.isLoading ? (
            <LoadingRow />
          ) : experiments.error ? (
            <ErrorNote>{(experiments.error as Error).message}</ErrorNote>
          ) : recentExperiments.length === 0 ? (
            <EmptyState
              icon={<FlaskConical className="h-6 w-6" />}
              title="还没有实验记录"
              description="记录目标、假设、方法、指标、问题与失败原因，之后可以用自然语言检索历史，例如「之前为什么放弃这个方案」。"
              action={
                <Link to="/experiments">
                  <Button size="sm" variant="secondary">前往实验中心</Button>
                </Link>
              }
            />
          ) : (
            <ul className="divide-y divide-ink-800/70">
              {recentExperiments.map((exp) => (
                <li key={exp.experiment_id} className="py-2.5">
                  <div className="flex items-start justify-between gap-3">
                    <p className="min-w-0 truncate text-xs font-medium text-ink-100">{exp.name}</p>
                    <span className={cn('shrink-0 rounded-md px-2 py-0.5 text-[11px]', STATUS_STYLES[exp.status] ?? STATUS_STYLES.planned)}>
                      {STATUS_LABELS[exp.status] ?? exp.status}
                    </span>
                  </div>
                  <p className="lt-muted mt-1 text-[11px]">
                    {exp.dataset ? `${exp.dataset} · ` : ''}
                    {exp.metrics ? Object.entries(exp.metrics).map(([k, v]) => `${k}=${v}`).join(' ') : '暂无指标'}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <MemoryColumn
          title="下一步计划"
          icon={<ListChecks className="h-4 w-4" />}
          entries={nextActions}
          loading={memories.isLoading}
          empty="保存一次研究进度后，这里会显示待办事项"
        />
        <MemoryColumn
          title="最近研究决策"
          icon={<Brain className="h-4 w-4" />}
          entries={decisions}
          loading={memories.isLoading}
          empty="在实验中心点击「写入 PowerContext 记忆」可沉淀决策"
        />
        <MemoryColumn
          title="失败记录"
          icon={<Activity className="h-4 w-4" />}
          entries={failures}
          loading={memories.isLoading}
          empty="失败或被放弃的实验会在这里留下可追溯的原因"
          tone="warn"
        />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Link to="/research">
          <Button variant="secondary" size="sm">打开 AI 科研助手</Button>
        </Link>
        <Link to="/reports">
          <Button variant="ghost" size="sm">生成本周科研周报</Button>
        </Link>
        <Link to="/memory">
          <Button variant="ghost" size="sm">查看全部长期记忆</Button>
        </Link>
        <span className="lt-muted ml-auto text-[11px]">
          项目共 {projects.length} 个 · 记忆按 PowerContext Scope 隔离
        </span>
      </div>

      <Modal
        open={Boolean(restored)}
        onClose={() => setRestored(null)}
        title="已恢复的研究上下文"
        description={
          restored
            ? `来源：PowerContext Scope ${restored.scope_id} · 恢复于 ${formatDate(restored.restored_at)}`
            : undefined
        }
        size="xl"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRestored(null)}>关闭</Button>
            <Link to="/research">
              <Button onClick={() => setRestored(null)}>带着上下文进入 AI 助手</Button>
            </Link>
          </>
        }
      >
        {restored ? <RestoredView result={restored} /> : null}
      </Modal>
    </div>
  )
}

function RestoredView({ result }: { result: RestoreResult }) {
  const handoff = result.handoff?.content
  return (
    <div className="space-y-5">
      {result.handoff_error ? (
        <ErrorNote>Handoff 读取失败：{result.handoff_error}（下方仍展示已恢复的记忆条目）</ErrorNote>
      ) : null}
      {handoff ? (
        <Card className="bg-ink-900/60">
          <CardHeader title="Handoff 历史快照" subtitle="保留上次会话状态；后续研究以当前有效记忆为准" />
          {handoff.objective ? (
            <div className="mb-3">
              <p className="lt-label">研究目标</p>
              <p className="text-xs text-ink-200">{handoff.objective}</p>
            </div>
          ) : null}
          {handoff.state?.length ? (
            <ul className="mb-3 space-y-1">
              {handoff.state.map((item, index) => (
                <li key={index} className="flex gap-2 text-xs text-ink-200">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-accent-400" />
                  {item.text}
                </li>
              ))}
            </ul>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-3">
            {handoff.disposition ? (
              <div>
                <p className="lt-label">当前状态</p>
                <p className="text-xs text-ink-200">{handoff.disposition}</p>
              </div>
            ) : null}
            {handoff.next_action?.text ? (
              <div>
                <p className="lt-label">下一步</p>
                <p className="text-xs text-ink-200">{handoff.next_action.text}</p>
              </div>
            ) : null}
            {handoff.omissions?.length ? (
              <div>
                <p className="lt-label">已知的信息缺口</p>
                {handoff.omissions.map((item, index) => <p key={index} className="text-xs text-ink-200">{item.text}</p>)}
              </div>
            ) : null}
          </div>
        </Card>
      ) : null}

      <div>
        <p className="lt-label mb-2">恢复的长期记忆（{result.memories.length} 条）</p>
        {result.memories.length === 0 ? (
          <EmptyState title="该项目还没有已保存的记忆" description="在 AI 助手页面完成一次会话后点击「保存本次研究进度」。" />
        ) : (
          <ul className="space-y-2">
            {result.memories.map((entry, index) => (
              <li key={index} className="rounded-lg border border-ink-700/70 bg-ink-900/50 px-3 py-2">
                <div className="mb-1 flex items-center gap-2">
                  <Badge tone="accent">{entry.kind_label ?? KIND_LABELS[entry.kind] ?? entry.kind}</Badge>
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
          <p className="lt-label mb-2">PreparedContext（PowerContext 组织后的上下文）</p>
          <div className="rounded-lg border border-ink-700/70 bg-ink-950/60 p-3">
            <Markdown content={result.prepared_context.content} className="text-xs" />
          </div>
        </div>
      ) : (
        <div>
          <p className="lt-label mb-2">PreparedContext</p>
          <p className="rounded-lg border border-ink-700/70 bg-ink-950/60 p-3 text-xs leading-relaxed text-ink-300">
            PowerContext 返回 status={result.prepared_context?.status ?? 'unavailable'}、内容为空。上下文组装依赖服务端的
            extract / topic-memory 能力，未给 PowerContext 配置模型提供方时按官方约定返回空结果；本次恢复改由上方的
            Handoff 与记忆条目提供，二者都是 PowerContext 中的真实记录。
          </p>
        </div>
      )}
    </div>
  )
}

function MemoryColumn({
  title,
  icon,
  entries,
  loading,
  empty,
  tone = 'neutral',
}: {
  title: string
  icon: React.ReactNode
  entries: { text: string; kind: string; kind_label?: string; version?: number }[]
  loading: boolean
  empty: string
  tone?: 'neutral' | 'warn'
}) {
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            {icon} {title}
          </span>
        }
        subtitle={loading ? '读取 PowerContext…' : `${entries.length} 条`}
      />
      {loading ? (
        <LoadingRow />
      ) : entries.length === 0 ? (
        <p className="lt-muted text-xs leading-relaxed">{empty}</p>
      ) : (
        <ul className="space-y-2">
          {entries.slice(0, 5).map((entry, index) => (
            <li key={index} className={cn('rounded-lg border px-3 py-2 text-xs leading-relaxed', tone === 'warn' ? 'border-amber-500/25 bg-amber-500/5 text-amber-100/90' : 'border-ink-700/70 bg-ink-900/50 text-ink-200')}>
              {entry.text}
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function LoadingRow() {
  return (
    <div className="flex items-center gap-2 py-3 text-xs text-ink-400">
      <Spinner className="h-3.5 w-3.5" /> 加载中…
    </div>
  )
}

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Boxes,
  Brain,
  CheckCircle2,
  Cpu,
  Database,
  FolderTree,
  Plus,
  ShieldCheck,
  Trash2,
  XCircle,
} from 'lucide-react'
import { api, type Project } from '@/lib/api'
import { useApp } from '@/state/AppContext'
import { useToast } from '@/components/ui/Toast'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ErrorNote,
  Input,
  Spinner,
  Textarea,
} from '@/components/ui/primitives'
import { Modal } from '@/components/ui/Modal'
import { formatDate } from '@/lib/utils'

export function Settings() {
  const { health, healthLoading, projects, projectsLoading, projectsError, currentProjectId, refreshProjects } = useApp()
  const toast = useToast()
  const [creating, setCreating] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<Project | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: 300_000 })

  const confirmDelete = async () => {
    if (!pendingDelete) return
    setDeleting(true)
    setDeleteError(null)
    try {
      const result = await api.deleteProject(pendingDelete.project_id)
      const detail =
        result.retired_memories > 0
          ? `，并退役了 ${result.retired_memories} 条 PowerContext 记忆`
          : '（该项目没有可退役的记忆）'
      toast.push(`项目「${pendingDelete.name}」已删除：seekdb 中的资料分块与实验记录已清除${detail}`, 'success')
      if (result.memory_errors.length > 0) {
        toast.push(`${result.memory_errors.length} 条记忆退役失败，请在 PowerContext 中人工核查：${result.memory_errors[0]}`, 'error')
      }
      setPendingDelete(null)
      refreshProjects()
    } catch (error) {
      setDeleteError((error as Error).message)
      toast.push(`删除失败：${(error as Error).message}`, 'error')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="服务连接状态"
          subtitle="所有状态都来自后端 /api/health 的真实探测结果，每 30 秒刷新一次"
          action={
            health ? (
              <Badge tone={health.status === 'ok' ? 'success' : 'warn'}>
                {health.status === 'ok' ? '全部就绪' : '部分降级'}
              </Badge>
            ) : (
              <Badge tone="danger">未连接</Badge>
            )
          }
        />
        {healthLoading && !health ? (
          <div className="flex items-center gap-2 py-3 text-xs text-ink-400">
            <Spinner className="h-3.5 w-3.5" /> 正在探测服务…
          </div>
        ) : !health ? (
          <ErrorNote>
            无法连接 LabTrace 后端。请确认 uvicorn 已启动，并且前端代理指向正确的 API 地址（VITE_API_TARGET）。
          </ErrorNote>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <StatusTile
              icon={<Database className="h-4 w-4" />}
              title="OceanBase seekdb"
              ok={health.seekdb.connected}
              okText="已连接"
              failText="未连接"
              lines={[`模式：${health.seekdb.mode}`, `版本：${health.seekdb.version}`]}
              hint="承载论文分块、全文索引、向量索引与实验记录"
            />
            <StatusTile
              icon={<Brain className="h-4 w-4" />}
              title="PowerContext"
              ok={health.powercontext.ready}
              okText={health.powercontext.reachable ? '就绪' : '可访问但未就绪'}
              failText={health.powercontext.reachable ? '可访问但未就绪' : '不可达'}
              lines={[`地址：${health.powercontext.url}`]}
              hint="承载研究状态、长期记忆、决策与跨会话接续"
            />
            <StatusTile
              icon={<Cpu className="h-4 w-4" />}
              title="大模型（可选）"
              ok={health.llm.configured}
              okText="已配置"
              failText="未配置"
              lines={[
                health.llm.model ? `模型：${health.llm.model}` : '模型：—',
                health.llm.base_url ? `Base URL：${health.llm.base_url}` : 'Base URL：—',
              ]}
              hint="未配置时资料导入、检索、实验记录与记忆读写仍可正常使用"
            />
            <StatusTile
              icon={<Boxes className="h-4 w-4" />}
              title="嵌入服务"
              ok
              okText={health.embedding.provider}
              failText=""
              lines={[`向量维度：${health.embedding.dimension}`]}
              hint={
                health.embedding.provider === 'local-hash-fallback'
                  ? '当前为本地确定性哈希回退，向量检索可用但语义区分度有限；配置 EMBEDDING_API_KEY 后会切换为真实嵌入模型'
                  : '使用 OpenAI 兼容嵌入接口生成向量'
              }
            />
          </div>
        )}
      </Card>

      <Card>
        <CardHeader
          title="运行时配置"
          subtitle="来自后端 /api/meta。敏感配置（API Key、数据库口令）只存在于服务端环境变量，不下发到浏览器"
        />
        {meta.isLoading ? (
          <div className="flex items-center gap-2 py-3 text-xs text-ink-400">
            <Spinner className="h-3.5 w-3.5" /> 读取配置…
          </div>
        ) : meta.error ? (
          <ErrorNote>{(meta.error as Error).message}</ErrorNote>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <tbody className="divide-y divide-ink-800/70">
                {Object.entries(meta.data ?? {}).map(([key, value]) => (
                  <tr key={key}>
                    <td className="lt-label w-64 py-2 pr-3 font-mono text-[11px] font-medium">{key}</td>
                    <td className="py-2 font-mono text-[11px] text-ink-200">{String(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <CardHeader
          title="研究项目"
          subtitle="每个项目对应一个独立的 PowerContext Scope 与 seekdb 数据分区，删除项目会同时清理两侧数据"
          action={
            <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setCreating(true)}>
              新建项目
            </Button>
          }
        />
        {projectsLoading ? (
          <div className="flex items-center gap-2 py-3 text-xs text-ink-400">
            <Spinner className="h-3.5 w-3.5" /> 加载项目…
          </div>
        ) : projectsError ? (
          <ErrorNote>{projectsError}</ErrorNote>
        ) : (
          <div className="space-y-2">
            {projects.map((project) => (
              <div
                key={project.project_id}
                className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-ink-700/70 bg-ink-900/50 px-3 py-2.5"
              >
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-xs font-medium text-ink-100">
                    {project.name}
                    {project.project_id === currentProjectId ? <Badge tone="accent">当前</Badge> : null}
                  </p>
                  {project.description ? <p className="lt-muted mt-0.5 text-[11px]">{project.description}</p> : null}
                  <p className="lt-muted mt-1 font-mono text-[10px]">
                    {project.project_id}
                    {project.pc_scope_id ? ` · scope ${project.pc_scope_id}` : ' · 未绑定 Scope'}
                    {` · ${project.document_count ?? 0} 资料 / ${project.experiment_count ?? 0} 实验 · ${formatDate(project.created_at)}`}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Trash2 className="h-3.5 w-3.5 text-rose-400" />}
                  onClick={() => {
                    setDeleteError(null)
                    setPendingDelete(project)
                  }}
                >
                  删除
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader
          title={<span className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-emerald-400" /> 数据隔离与安全</span>}
          subtitle="公开演示前请确认这些约束"
        />
        <ul className="space-y-2 text-xs leading-relaxed text-ink-300">
          <li className="flex gap-2">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
            所有科研数据按项目隔离：seekdb 侧每张表都带 <span className="font-mono text-accent-300">project_id</span>，检索与写入都会强制带上该条件；PowerContext 侧每个项目绑定独立 Scope。
          </li>
          <li className="flex gap-2">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
            数据库操作全部使用参数化查询，不拼接不可信 SQL；向量以字面量字符串传入，全文检索关键词作为绑定参数。
          </li>
          <li className="flex gap-2">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
            上传文件在服务端校验扩展名与大小上限，超限或类型不符会被拒绝。
          </li>
          <li className="flex gap-2">
            <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
            AI 生成的答案与原始证据分离保存：答案在 <span className="font-mono text-accent-300">answer</span>，证据在 <span className="font-mono text-accent-300">citations</span> 与 <span className="font-mono text-accent-300">data_sources</span>，可独立核对。
          </li>
          <li className="flex gap-2">
            <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
            对外公开演示时，请只使用仓库 <span className="font-mono text-accent-300">qoder/samples/</span> 中明确标注为示例的资料，不要上传私人研究数据。
          </li>
        </ul>
      </Card>

      <CreateProjectModal
        open={creating}
        onClose={() => setCreating(false)}
        onDone={() => {
          setCreating(false)
          refreshProjects()
        }}
      />

      <Modal
        open={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        title="删除研究项目"
        description="该操作不可撤销，会同时清理 seekdb 与 PowerContext 两侧的数据。"
        footer={
          <>
            <Button variant="ghost" disabled={deleting} onClick={() => setPendingDelete(null)}>取消</Button>
            <Button variant="danger" loading={deleting} onClick={confirmDelete}>确认删除</Button>
          </>
        }
      >
        <div className="space-y-3">
          <p className="text-xs leading-relaxed text-ink-200">
            即将删除项目「<span className="font-medium text-rose-300">{pendingDelete?.name}</span>
            」，以下内容会被清除：
          </p>
          <ul className="space-y-1.5 text-xs text-ink-300">
            <li className="flex gap-2">
              <FolderTree className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-500" />
              seekdb：项目记录、全部资料分块（含向量与全文索引）、全部实验记录
            </li>
            <li className="flex gap-2">
              <Brain className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-500" />
              PowerContext：该项目 Scope 下的长期记忆会逐条退役（保留历史版本以便追溯）
            </li>
          </ul>
          {deleteError ? <ErrorNote>{deleteError}</ErrorNote> : null}
        </div>
      </Modal>
    </div>
  )
}

function StatusTile({
  icon,
  title,
  ok,
  okText,
  failText,
  lines,
  hint,
}: {
  icon: React.ReactNode
  title: string
  ok: boolean
  okText: string
  failText: string
  lines: string[]
  hint: string
}) {
  return (
    <div className={`rounded-lg border px-3 py-2.5 ${ok ? 'border-emerald-500/25 bg-emerald-500/5' : 'border-rose-500/25 bg-rose-500/5'}`}>
      <p className="flex items-center gap-2 text-xs font-medium text-ink-100">
        <span className={ok ? 'text-emerald-400' : 'text-rose-400'}>{icon}</span>
        {title}
      </p>
      <p className={`mt-1 text-[11px] font-medium ${ok ? 'text-emerald-300' : 'text-rose-300'}`}>{ok ? okText : failText}</p>
      <div className="mt-1.5 space-y-0.5">
        {lines.map((line) => (
          <p key={line} className="lt-muted break-all font-mono text-[10px]">{line}</p>
        ))}
      </div>
      <p className="lt-muted mt-2 text-[10px] leading-relaxed">{hint}</p>
    </div>
  )
}

function CreateProjectModal({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast()
  const { setCurrentProjectId } = useApp()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [profile, setProfile] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      const project = await api.createProject({
        name: name.trim(),
        description: description.trim() || undefined,
        research_profile: profile.trim() || undefined,
      })
      setCurrentProjectId(project.project_id)
      toast.push(
        project.pc_scope_id
          ? `项目「${project.name}」已创建并绑定 PowerContext Scope ${project.pc_scope_id}`
          : `项目「${project.name}」已创建，但 PowerContext Scope 绑定失败：长期记忆功能不可用`,
        project.pc_scope_id ? 'success' : 'error',
      )
      setName('')
      setDescription('')
      setProfile('')
      onDone()
    } catch (err) {
      setError((err as Error).message)
      toast.push(`创建失败：${(err as Error).message}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="新建研究项目"
      description="项目是数据隔离的边界：独立的 seekdb 分区与 PowerContext Scope。"
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={onClose}>取消</Button>
          <Button loading={busy} disabled={!name.trim()} onClick={submit}>创建项目</Button>
        </>
      }
    >
      <div className="space-y-4">
        <Input label="项目名称 *" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：3D-MEM 场景记忆研究" autoFocus />
        <Textarea label="项目背景" rows={3} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="研究任务与背景" />
        <Textarea
          label="研究方向（Research Profile）"
          rows={4}
          value={profile}
          onChange={(event) => setProfile(event.target.value)}
          placeholder="例如：研究 Embodied Question Answering 中的 3D 场景记忆机制"
          hint="创建后作为 research_profile 记忆写入 PowerContext"
        />
        {error ? <ErrorNote>{error}</ErrorNote> : null}
      </div>
    </Modal>
  )
}

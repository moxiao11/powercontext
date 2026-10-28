import { NavLink, useLocation } from 'react-router-dom'
import {
  BookOpen,
  Brain,
  ChevronDown,
  FlaskConical,
  LayoutDashboard,
  Moon,
  Plus,
  Settings as SettingsIcon,
  Sparkles,
  Sun,
  FileText,
  Activity,
  Menu,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { cn } from '@/lib/utils'
import { useApp } from '@/state/AppContext'
import { api } from '@/lib/api'
import { Button, Input, Spinner, Textarea } from '@/components/ui/primitives'
import { Modal } from '@/components/ui/Modal'
import { useToast } from '@/components/ui/Toast'

const NAV = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, hint: '科研总览' },
  { to: '/library', label: 'Library', icon: BookOpen, hint: '论文知识库' },
  { to: '/experiments', label: 'Experiments', icon: FlaskConical, hint: '实验中心' },
  { to: '/research', label: 'AI Research', icon: Sparkles, hint: '科研助手' },
  { to: '/memory', label: 'Memory', icon: Brain, hint: '长期记忆' },
  { to: '/reports', label: 'Reports', icon: FileText, hint: '科研周报' },
  { to: '/settings', label: 'Settings', icon: SettingsIcon, hint: '系统设置' },
]

export function AppLayout({ children }: { children: React.ReactNode }) {
  const { theme, toggleTheme, health } = useApp()
  const location = useLocation()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  useEffect(() => setSidebarOpen(false), [location.pathname])
  const active = NAV.find((item) => (item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to)))

  return (
    <div className="flex min-h-screen">
      {sidebarOpen ? <button aria-label="关闭导航遮罩" onClick={() => setSidebarOpen(false)} className="fixed inset-0 z-40 bg-black/60 md:hidden" /> : null}
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-ink-800/80 bg-ink-950/80 px-4 backdrop-blur-md md:px-6">
          <div className="flex items-baseline gap-3">
            <button aria-label="打开导航" aria-expanded={sidebarOpen} onClick={() => setSidebarOpen(true)} className="self-center text-ink-300 md:hidden"><Menu className="h-5 w-5" /></button>
            <h1 className="text-sm font-semibold text-ink-100">{active?.label ?? 'LabTrace'}</h1>
            <span className="lt-muted text-xs">{active?.hint}</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden sm:block"><ConnectionStatus health={health} /></div>
            <button
              onClick={toggleTheme}
              className="rounded-lg border border-ink-700 p-1.5 text-ink-300 transition hover:border-ink-600 hover:text-ink-100"
              aria-label="切换主题"
            >
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
          </div>
        </header>
        <main className="min-w-0 flex-1 px-4 py-5 md:px-6 md:py-6">{children}</main>
      </div>
    </div>
  )
}

function ConnectionStatus({ health }: { health: ReturnType<typeof useApp>['health'] }) {
  if (!health) return <span className="lt-label flex items-center gap-1.5"><Spinner className="h-3 w-3" /> 检测服务…</span>
  const seekdbOk = health.seekdb.connected
  const pcOk = health.powercontext.ready
  const tone = seekdbOk && pcOk ? 'bg-emerald-400' : seekdbOk ? 'bg-amber-400' : 'bg-rose-400'
  return (
    <div className="flex items-center gap-3 text-[11px] text-ink-400">
      <span className="flex items-center gap-1.5" title={`OceanBase seekdb ${health.seekdb.version} (${health.seekdb.mode})`}>
        <span className={cn('h-1.5 w-1.5 rounded-full', seekdbOk ? 'bg-emerald-400' : 'bg-rose-400')} />
        seekdb
      </span>
      <span className="flex items-center gap-1.5" title={`PowerContext ${health.powercontext.url}`}>
        <span className={cn('h-1.5 w-1.5 rounded-full', pcOk ? 'bg-emerald-400' : 'bg-rose-400')} />
        PowerContext
      </span>
      <span className="flex items-center gap-1.5" title={health.llm.configured ? `LLM ${health.llm.model}` : '未配置大模型 API'}>
        <span className={cn('h-1.5 w-1.5 rounded-full', health.llm.configured ? tone : 'bg-ink-600')} />
        LLM
      </span>
    </div>
  )
}

function Sidebar({ open: drawerOpen, onClose }: { open: boolean; onClose: () => void }) {
  const { projects, currentProject, currentProjectId, setCurrentProjectId, projectsLoading, refreshProjects } = useApp()
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const toast = useToast()
  const queryClient = useQueryClient()

  return (
    <aside className={cn('fixed inset-y-0 left-0 z-50 flex h-screen w-60 shrink-0 flex-col border-r border-ink-800/80 bg-ink-950 transition-transform md:sticky md:top-0 md:z-auto md:translate-x-0 md:bg-ink-900/40', drawerOpen ? 'translate-x-0' : '-translate-x-full')}>
      <div className="flex h-14 items-center gap-2.5 border-b border-ink-800/80 px-5">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-accent-500 to-sky-500 shadow-glow">
          <Activity className="h-4 w-4 text-white" />
        </div>
        <div className="leading-tight">
          <p className="text-sm font-semibold tracking-tight text-ink-50">LabTrace</p>
          <p className="text-[10px] text-ink-400">科研记忆工作台</p>
        </div>
        <button onClick={onClose} aria-label="关闭导航" className="ml-auto text-ink-300 md:hidden"><X className="h-4 w-4" /></button>
      </div>

      <div className="px-3 py-3">
        <div className="lt-panel relative">
          <button
            onClick={() => setOpen((value) => !value)}
            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
          >
            <span className="min-w-0">
              <span className="lt-label block">当前研究项目</span>
              <span className="block truncate text-xs font-medium text-ink-100">
                {projectsLoading ? '加载中…' : currentProject?.name ?? '未选择项目'}
              </span>
            </span>
            <ChevronDown className={cn('h-4 w-4 shrink-0 text-ink-400 transition', open && 'rotate-180')} />
          </button>
          {open ? (
            <div className="animate-fade-in border-t border-ink-700/60 py-1">
              {projects.map((project) => (
                <button
                  key={project.project_id}
                  onClick={() => {
                    setCurrentProjectId(project.project_id)
                    setOpen(false)
                    queryClient.invalidateQueries()
                  }}
                  className={cn(
                    'flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-xs transition hover:bg-ink-800/70',
                    project.project_id === currentProjectId ? 'text-accent-300' : 'text-ink-300',
                  )}
                >
                  <span className="truncate">{project.name}</span>
                  {project.pc_scope_id ? <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400" title="已绑定 PowerContext Scope" /> : <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-rose-400" title="未绑定 Scope" />}
                </button>
              ))}
              <button
                onClick={() => {
                  setCreating(true)
                  setOpen(false)
                }}
                className="flex w-full items-center gap-2 border-t border-ink-700/60 px-3 py-2 text-xs text-ink-300 transition hover:bg-ink-800/70 hover:text-ink-100"
              >
                <Plus className="h-3.5 w-3.5" /> 新建研究项目
              </button>
            </div>
          ) : null}
        </div>
      </div>

      <nav className="flex-1 space-y-0.5 px-3">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-all',
                isActive
                  ? 'bg-accent-500/12 text-accent-300 shadow-[inset_0_0_0_1px_rgba(124,92,252,0.25)]'
                  : 'text-ink-300 hover:bg-ink-800/60 hover:text-ink-100',
              )
            }
          >
            <item.icon className="h-4 w-4" />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-ink-800/80 px-5 py-3 text-[10px] leading-relaxed text-ink-500">
        OceanBase seekdb · PowerContext
        <br />
        Qoder × OceanBase 2026
      </div>

      <CreateProjectModal
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(project) => {
          setCurrentProjectId(project.project_id)
          refreshProjects()
          toast.push(`项目「${project.name}」已创建${project.pc_scope_id ? '，并已绑定 PowerContext Scope' : '，但 PowerContext Scope 绑定失败'}`, project.pc_scope_id ? 'success' : 'error')
        }}
      />
    </aside>
  )
}

function CreateProjectModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (project: Awaited<ReturnType<typeof api.createProject>>) => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [profile, setProfile] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!name.trim()) return
    setBusy(true)
    try {
      const project = await api.createProject({
        name: name.trim(),
        description: description.trim() || undefined,
        research_profile: profile.trim() || undefined,
      })
      onCreated(project)
      setName('')
      setDescription('')
      setProfile('')
      onClose()
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="新建研究项目"
      description="每个项目拥有独立的 seekdb 数据分区与 PowerContext Scope，记忆互不干扰。"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>取消</Button>
          <Button onClick={submit} loading={busy} disabled={!name.trim()}>创建项目</Button>
        </>
      }
    >
      <div className="space-y-4">
        <Input label="项目名称" value={name} onChange={(e) => setName(e.target.value)} placeholder="例如：3D-MEM 场景记忆研究" autoFocus />
        <Textarea label="项目背景" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="研究任务与背景，将写入 PowerContext Scope 摘要" />
        <Textarea
          label="研究方向（Research Profile）"
          rows={4}
          value={profile}
          onChange={(e) => setProfile(e.target.value)}
          placeholder="例如：研究 Embodied Question Answering 中的 3D 场景记忆机制，目标是提升长时序问答准确率"
          hint="创建后作为 research_profile 记忆写入 PowerContext"
        />
      </div>
    </Modal>
  )
}

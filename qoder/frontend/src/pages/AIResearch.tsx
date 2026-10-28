import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen,
  Brain,
  Database,
  Send,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { api, type ChatResponse, type Citation } from '@/lib/api'
import { useApp } from '@/state/AppContext'
import { useToast } from '@/components/ui/Toast'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  Spinner,
  Textarea,
} from '@/components/ui/primitives'
import { Modal } from '@/components/ui/Modal'
import { Markdown } from '@/components/Markdown'
import { formatDate } from '@/lib/utils'

const INTENT_LABELS: Record<string, string> = {
  paper: '论文知识',
  experiment: '实验记录',
  memory: '研究进度',
  mixed: '综合（多源）',
  general: '通用',
}

const SAMPLE_QUESTIONS = [
  '根据已导入的论文，3D 场景记忆如何提升长时序问答准确率？',
  '之前为什么放弃纯 2D 特征方案？',
  '我上次研究到哪里了，下一步应该做什么？',
]

interface Turn {
  role: 'user' | 'assistant'
  content: string
  response?: ChatResponse
}

export function AIResearch() {
  const { currentProject, health } = useApp()
  const projectId = currentProject?.project_id ?? null
  const toast = useToast()
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [selected, setSelected] = useState<ChatResponse | null>(null)
  const [saveOpen, setSaveOpen] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setTurns([])
    setSessionId(null)
    setSelected(null)
  }, [projectId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns, busy])

  const ask = async (question: string) => {
    const text = question.trim()
    if (!projectId || !text || busy) return
    setInput('')
    setBusy(true)
    setTurns((current) => [...current, { role: 'user', content: text }])
    try {
      const response = await api.chat({
        project_id: projectId,
        message: text,
        session_id: sessionId ?? undefined,
      })
      setSessionId(response.session_id)
      setTurns((current) => [...current, { role: 'assistant', content: response.answer, response }])
      setSelected(response)
    } catch (error) {
      const message = (error as Error).message
      setTurns((current) => [...current, { role: 'assistant', content: `请求失败：${message}` }])
      toast.push(`提问失败：${message}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  const clearSession = async () => {
    if (!sessionId) {
      setTurns([])
      setSelected(null)
      return
    }
    try {
      await api.clearSession(sessionId)
    } catch {
      /* the local conversation is dropped regardless; server-side history is best effort */
    }
    setSessionId(null)
    setTurns([])
    setSelected(null)
    toast.push('已清空当前会话（PowerContext 中的长期记忆不受影响）', 'info')
  }

  if (!currentProject) {
    return <EmptyState icon={<Sparkles className="h-8 w-8" />} title="请先选择研究项目" description="AI 科研助手会在当前项目的 seekdb 数据与 PowerContext Scope 内检索证据。" />
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="space-y-4">
        <Card>
          <CardHeader
            title="AI 科研助手"
            subtitle="按问题类型路由数据源：论文与实验走 seekdb，研究进度走 PowerContext，复杂问题两者并用"
            action={
              sessionId ? <Badge tone="info">会话 {sessionId.slice(0, 12)}…</Badge> : <Badge>新会话</Badge>
            }
          />
          {!health?.llm.configured ? (
            <div className="mb-3">
              <ErrorNote>
                未配置大模型 API：系统仍可完成检索并返回真实证据，但答案部分会降级为证据摘录，不会生成结论。资料导入、seekdb
                检索、实验记录与 PowerContext 记忆读写均不受影响。
              </ErrorNote>
            </div>
          ) : null}
          <div className="flex items-end gap-2">
            <Textarea
              rows={2}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  void ask(input)
                }
              }}
              placeholder="提出一个研究问题，Enter 发送，Shift+Enter 换行"
              className="flex-1"
              aria-label="研究问题"
            />
            <Button onClick={() => ask(input)} loading={busy} disabled={!input.trim()} icon={<Send className="h-4 w-4" />}>
              提问
            </Button>
          </div>
          {turns.length === 0 ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {SAMPLE_QUESTIONS.map((question) => (
                <button
                  key={question}
                  onClick={() => ask(question)}
                  disabled={busy}
                  className="rounded-lg border border-ink-700 bg-ink-900/50 px-2.5 py-1.5 text-left text-[11px] text-ink-300 transition hover:border-accent-500/40 hover:text-accent-200 disabled:opacity-50"
                >
                  {question}
                </button>
              ))}
            </div>
          ) : null}
        </Card>

        <div className="space-y-3">
          {turns.map((turn, index) =>
            turn.role === 'user' ? (
              <div key={index} className="flex justify-end">
                <div className="max-w-[80%] rounded-xl rounded-br-sm border border-accent-500/30 bg-accent-500/10 px-3.5 py-2.5 text-xs leading-relaxed text-ink-100">
                  {turn.content}
                </div>
              </div>
            ) : (
              <div key={index} className="lt-card px-4 py-3">
                {turn.response ? (
                  <div className="mb-2 flex flex-wrap items-center gap-2">
                    <Badge tone="accent">{INTENT_LABELS[turn.response.intent] ?? turn.response.intent}</Badge>
                    <Badge tone={turn.response.llm_used ? 'success' : 'warn'}>
                      {turn.response.llm_used ? '大模型生成' : '证据直出（未调用大模型）'}
                    </Badge>
                    <Badge tone="info">{turn.response.citations.length} 条引用</Badge>
                    <Badge>{turn.response.data_sources.length} 个数据源</Badge>
                    <button
                      onClick={() => setSelected(turn.response!)}
                      className="ml-auto text-[11px] text-accent-300 transition hover:text-accent-400"
                    >
                      查看解释面板
                    </button>
                  </div>
                ) : null}
                <Markdown content={turn.content} className="text-xs" />
                {turn.response?.notice ? (
                  <p className="mt-2 rounded-lg border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-[11px] leading-relaxed text-amber-100/90">
                    {turn.response.notice}
                  </p>
                ) : null}
                {turn.response?.llm_error ? (
                  <div className="mt-2"><ErrorNote>大模型调用失败，已降级为证据摘录：{turn.response.llm_error}</ErrorNote></div>
                ) : null}
                {turn.response && turn.response.citations.length > 0 ? (
                  <CitationList citations={turn.response.citations} />
                ) : null}
              </div>
            ),
          )}
          {busy ? (
            <div className="lt-card flex items-center gap-2 px-4 py-3 text-xs text-ink-400">
              <Spinner className="h-3.5 w-3.5" /> 正在检索 seekdb 与 PowerContext…
            </div>
          ) : null}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="space-y-4">
        <Card>
          <CardHeader title="会话操作" subtitle="长期记忆保存在 PowerContext，与会话无关，可在新会话中恢复" />
          <div className="flex flex-col gap-2">
            <Button icon={<Brain className="h-4 w-4" />} onClick={() => setSaveOpen(true)} disabled={turns.length === 0}>
              保存本次研究进度
            </Button>
            <Button variant="secondary" icon={<Trash2 className="h-4 w-4" />} onClick={clearSession} disabled={turns.length === 0}>
              清空当前会话
            </Button>
          </div>
          {turns.length === 0 ? (
            <p className="lt-muted mt-3 text-[11px] leading-relaxed">
              先提几个问题，再保存进度：系统会把本次会话的结论、决策、失败与下一步写入 PowerContext，并生成一条可跨会话延续的 Handoff 记录。
            </p>
          ) : null}
        </Card>

        <ExplainPanel response={selected} />
      </div>

      <SaveProgressModal
        open={saveOpen}
        projectId={projectId}
        sessionId={sessionId}
        turns={turns}
        onClose={() => setSaveOpen(false)}
      />
    </div>
  )
}

function CitationList({ citations }: { citations: Citation[] }) {
  const [open, setOpen] = useState<number | null>(null)
  return (
    <div className="mt-3 border-t border-ink-700/70 pt-2.5">
      <p className="lt-label mb-1.5">引用证据（seekdb / PowerContext 的真实记录）</p>
      <ul className="space-y-1.5">
        {citations.map((citation, index) => {
          const expanded = open === index
          return (
            <li key={citation.chunk_id ?? index}>
              <button
                onClick={() => setOpen(expanded ? null : index)}
                className="flex w-full items-start gap-2 rounded-lg border border-ink-700/60 bg-ink-900/40 px-2.5 py-1.5 text-left transition hover:border-accent-500/30"
              >
                <span className="mt-0.5 shrink-0 rounded bg-accent-500/20 px-1.5 py-0.5 font-mono text-[10px] text-accent-300">[{index + 1}]</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[11px] font-medium text-ink-100">
                    {citation.title ?? citation.label ?? '记忆 / 实验记录'}
                  </span>
                  <span className="lt-muted block truncate text-[10px]">
                    {citation.location ?? citation.type ?? ''}
                    {citation.topic ? ` · ${citation.topic}` : ''}
                    {typeof citation.score === 'number' ? ` · score ${citation.score.toFixed(3)}` : ''}
                  </span>
                </span>
              </button>
              {expanded ? (
                <p className="animate-fade-in mt-1 whitespace-pre-wrap rounded-lg border border-ink-700/60 bg-ink-950/60 px-2.5 py-2 text-[11px] leading-relaxed text-ink-200">
                  {citation.excerpt ?? citation.content ?? '（无原文摘录）'}
                </p>
              ) : null}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

const SOURCE_ICONS: Record<string, typeof Database> = {
  'seekdb.document_chunks': BookOpen,
  'seekdb.experiments': Database,
}

function ExplainPanel({ response }: { response: ChatResponse | null }) {
  const [expanded, setExpanded] = useState<number | null>(null)
  useEffect(() => setExpanded(null), [response])

  if (!response) {
    return (
      <Card>
        <CardHeader title="解释面板" subtitle="当前回答使用了哪些数据" />
        <p className="lt-muted text-xs leading-relaxed">
          提一个问题后，这里会列出后端实际访问的数据源：seekdb 的论文分块与实验记录、PowerContext 的记忆与 PreparedContext，以及是否调用了大模型。点击数据源可展开原始记录。
        </p>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader
        title="解释面板"
        subtitle="当前回答使用了哪些数据"
        action={<Badge tone="accent">{INTENT_LABELS[response.intent] ?? response.intent}</Badge>}
      />
      <ul className="space-y-2">
        {response.data_sources.length === 0 ? (
          <li className="lt-muted text-xs">本次回答没有命中任何数据源。</li>
        ) : (
          response.data_sources.map((source, index) => {
            const Icon = SOURCE_ICONS[source.kind] ?? Brain
            const open = expanded === index
            return (
              <li key={index} className="rounded-lg border border-ink-700/70 bg-ink-900/50">
                <button
                  onClick={() => setExpanded(open ? null : index)}
                  className="flex w-full items-start gap-2 px-3 py-2 text-left transition hover:bg-ink-800/50"
                >
                  <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent-300" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-xs font-medium text-ink-100">{source.description}</span>
                    <span className="lt-muted block font-mono text-[10px]">
                      {source.kind} · {source.items.length} 条
                    </span>
                  </span>
                </button>
                {open ? (
                  <pre className="animate-fade-in max-h-64 overflow-auto border-t border-ink-700/70 px-3 py-2 font-mono text-[10px] leading-relaxed text-ink-300">
                    {JSON.stringify(source.items, null, 2)}
                  </pre>
                ) : null}
              </li>
            )
          })
        )}
      </ul>
      <div className="mt-3 space-y-1 border-t border-ink-700/70 pt-2.5 text-[11px] text-ink-400">
        <p>项目：{response.project_id}</p>
        <p>会话：{response.session_id}</p>
        <p>大模型：{response.llm_used ? '已调用' : '未调用（证据直出）'}</p>
      </div>
    </Card>
  )
}

function SaveProgressModal({
  open,
  projectId,
  sessionId,
  turns,
  onClose,
}: {
  open: boolean
  projectId: string | null
  sessionId: string | null
  turns: Turn[]
  onClose: () => void
}) {
  const toast = useToast()
  const [summary, setSummary] = useState('')
  const [completed, setCompleted] = useState('')
  const [conclusions, setConclusions] = useState('')
  const [decisions, setDecisions] = useState('')
  const [failures, setFailures] = useState('')
  const [openQuestions, setOpenQuestions] = useState('')
  const [nextSteps, setNextSteps] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const messages = useMemo(
    () =>
      turns
        .filter((turn) => turn.response || turn.role === 'user')
        .map((turn) => ({ role: turn.role, content: turn.content })),
    [turns],
  )

  useEffect(() => {
    if (!open) return
    setSummary(
      turns
        .filter((turn) => turn.role === 'assistant' && turn.response)
        .map((turn) => turn.content)
        .join('\n')
        .slice(0, 4000),
    )
  }, [open])

  const splitLines = (value: string) =>
    value
      .split('\n')
      .map((line) => line.replace(/^[-*\d.\s]+/, '').trim())
      .filter(Boolean)

  const splitPairs = (value: string) =>
    value
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const separator = line.search(/[：:]/)
        if (separator <= 0) return { text: line, reason: '' }
        return { text: line.slice(0, separator).trim(), reason: line.slice(separator + 1).trim() }
      })
      .filter((pair) => pair.text)

  const submit = async () => {
    if (!projectId) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.saveProgress({
        project_id: projectId,
        session_id: sessionId ?? `manual-${Date.now()}`,
        summary: summary.trim() || undefined,
        messages,
        completed: splitLines(completed),
        conclusions: splitLines(conclusions),
        decisions: splitPairs(decisions),
        failures: splitPairs(failures),
        open_questions: splitLines(openQuestions),
        next_steps: splitLines(nextSteps),
        evidence: { project_id: projectId, session_id: sessionId, origin: 'labtrace-ui' },
      })
      const committed = result.handoff?.status === 'committed'
      const failed = result.failed_writes?.length ?? 0
      const message = `已写入 ${result.memories.length} 条记忆；Handoff ${committed ? '已提交' : '未提交'}`
      if (result.status === 'partial' || failed || !committed) {
        setError(`${message}。${failed} 条记忆写入失败；会话原文已归档。请核对长期记忆后重试失败项。`)
        toast.push(message, 'info')
      } else {
        toast.push(`已保存研究进度：${message}`, 'success')
        onClose()
      }
    } catch (err) {
      setError((err as Error).message)
      toast.push(`保存失败：${(err as Error).message}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="保存本次研究进度"
      description="写入 PowerContext 长期记忆，并生成一条 Handoff 记录。新会话或重新打开工作台后都能恢复。"
      size="xl"
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={onClose}>取消</Button>
          <Button loading={busy} onClick={submit}>保存到 PowerContext</Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="lt-muted text-xs leading-relaxed">
          摘要已根据本次会话自动生成，可修改后再保存。每一项都会成为独立的记忆条目，一行一条；「决策」与「失败」建议写成
          <span className="font-mono text-accent-300"> 内容：原因 </span>
          的形式，便于日后追溯。
        </p>
        <Textarea label="本次会话摘要" rows={4} value={summary} onChange={(event) => setSummary(event.target.value)} />
        <Textarea label="已完成事项（一行一条）" rows={3} value={completed} onChange={(event) => setCompleted(event.target.value)} placeholder={'导入了 3 篇 EQA 相关论文\n完成 3DMem 消融实验'} />
        <Textarea label="研究结论（一行一条）" rows={3} value={conclusions} onChange={(event) => setConclusions(event.target.value)} placeholder="场景记忆在长时序问题上收益最大，短问题上基本持平" />
        <Textarea label="研究决策（内容：原因）" rows={3} value={decisions} onChange={(event) => setDecisions(event.target.value)} placeholder="采用 3D 场景记忆方案：长时序问答准确率高出基线 4.1 个点" />
        <Textarea label="失败记录（内容：原因）" rows={3} value={failures} onChange={(event) => setFailures(event.target.value)} placeholder="放弃纯 2D 特征方案：显存占用过高且长时序准确率下降" />
        <Textarea label="待解决的问题（一行一条）" rows={2} value={openQuestions} onChange={(event) => setOpenQuestions(event.target.value)} placeholder="记忆槽数量对推理延迟的影响还没测" />
        <Textarea label="下一步计划（一行一条）" rows={3} value={nextSteps} onChange={(event) => setNextSteps(event.target.value)} placeholder={'在 ScanQA 上复测\n补充消融：记忆槽 256 / 512 / 1024'} />
        {error ? <ErrorNote>{error}</ErrorNote> : null}
        <p className="lt-muted text-[11px]">会话消息 {messages.length} 条将作为 Source 一并归档到 PowerContext{sessionId ? `（会话 ${sessionId}，保存于 ${formatDate(new Date().toISOString())}）` : ''}。</p>
      </div>
    </Modal>
  )
}

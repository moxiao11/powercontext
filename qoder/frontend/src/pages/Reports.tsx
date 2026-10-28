import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { CalendarRange, Copy, Download, FileText, RefreshCw } from 'lucide-react'
import { api } from '@/lib/api'
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
  Textarea,
} from '@/components/ui/primitives'
import { Markdown } from '@/components/Markdown'
import { formatDay } from '@/lib/utils'

function isoDay(offsetDays = 0) {
  const date = new Date()
  date.setDate(date.getDate() + offsetDays)
  return date.toISOString().slice(0, 10)
}

export function Reports() {
  const { currentProject, health } = useApp()
  const projectId = currentProject?.project_id ?? null
  const toast = useToast()

  const defaultRange = useQuery({ queryKey: ['report-range'], queryFn: api.defaultReportRange, staleTime: 300_000 })
  const [start, setStart] = useState(isoDay(-6))
  const [end, setEnd] = useState(isoDay(0))
  const [title, setTitle] = useState('')
  const [markdown, setMarkdown] = useState('')
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [llmUsed, setLlmUsed] = useState(false)
  const [memoryError, setMemoryError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (defaultRange.data) {
      setStart(defaultRange.data.start_date)
      setEnd(defaultRange.data.end_date)
    }
  }, [defaultRange.data])

  useEffect(() => {
    setMarkdown('')
    setCounts({})
    setError(null)
    setMemoryError(null)
    setEditing(false)
  }, [projectId])

  const generate = async () => {
    if (!projectId) return
    if (start > end) {
      setError('开始日期不能晚于结束日期')
      return
    }
    setBusy(true)
    setError(null)
    setMemoryError(null)
    try {
      const result = await api.generateReport({
        project_id: projectId,
        start_date: start,
        end_date: end,
        title: title.trim() || undefined,
      })
      setMarkdown(result.markdown)
      setCounts(result.counts ?? {})
      setLlmUsed(result.llm_used)
      setMemoryError(result.memory_error ?? null)
      toast.push(
        `周报已生成：${result.counts?.documents ?? 0} 篇新资料、${result.counts?.experiments ?? 0} 组实验${result.llm_used ? '（含大模型总结）' : '（未配置大模型，纯记录汇总）'}`,
        'success',
      )
    } catch (err) {
      setError((err as Error).message)
      setMarkdown('')
      toast.push(`生成失败：${(err as Error).message}`, 'error')
    } finally {
      setBusy(false)
    }
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(markdown)
      toast.push('周报 Markdown 已复制到剪贴板', 'success')
    } catch {
      toast.push('浏览器拒绝了剪贴板访问，请手动选择文本复制', 'error')
    }
  }

  const download = () => {
    const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `LabTrace-周报-${start}_${end}.md`
    link.click()
    URL.revokeObjectURL(url)
    toast.push('已下载 Markdown 文件', 'success')
  }

  if (!currentProject) {
    return <EmptyState icon={<FileText className="h-8 w-8" />} title="请先选择研究项目" description="周报会汇总该项目在指定时间区间内的真实资料导入、实验记录与 PowerContext 记忆。" />
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="自动科研周报"
          subtitle="实验指标与已完成事项全部来自 seekdb 与 PowerContext 的真实记录，不会虚构"
          action={
            <Button size="sm" variant="secondary" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => defaultRange.refetch()}>
              使用默认区间
            </Button>
          }
        />
        <div className="flex flex-wrap items-end gap-3">
          <Input label="开始日期" type="date" value={start} onChange={(event) => setStart(event.target.value)} className="w-44" />
          <Input label="结束日期" type="date" value={end} onChange={(event) => setEnd(event.target.value)} className="w-44" />
          <div className="min-w-[220px] flex-1">
            <Input label="周报标题（可选）" value={title} onChange={(event) => setTitle(event.target.value)} placeholder={`例如：${currentProject.name} 周报`} />
          </div>
          <Button onClick={generate} loading={busy} icon={<CalendarRange className="h-4 w-4" />}>
            生成周报
          </Button>
        </div>
        {!health?.llm.configured ? (
          <p className="lt-muted mt-3 text-[11px] leading-relaxed">
            未配置大模型 API：周报仍会生成，内容为基于真实记录的统计与条目汇总，只是不含自动撰写的总结段落。
          </p>
        ) : null}
        {error ? <div className="mt-3"><ErrorNote>{error}</ErrorNote></div> : null}
      </Card>

      {markdown ? (
        <Card>
          <CardHeader
            title="周报预览"
            subtitle={`${formatDay(start)} — ${formatDay(end)}`}
            action={
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant={editing ? 'primary' : 'secondary'} onClick={() => setEditing((value) => !value)}>
                  {editing ? '返回预览' : '编辑'}
                </Button>
                <Button size="sm" variant="secondary" icon={<Copy className="h-3.5 w-3.5" />} onClick={copy}>
                  复制
                </Button>
                <Button size="sm" variant="secondary" icon={<Download className="h-3.5 w-3.5" />} onClick={download}>
                  下载 .md
                </Button>
              </div>
            }
          />
          <div className="mb-3 flex flex-wrap gap-2">
            <Badge tone={llmUsed ? 'success' : 'warn'}>{llmUsed ? '含大模型总结' : '纯记录汇总'}</Badge>
            {Object.entries(counts).map(([key, value]) => (
              <Badge key={key} tone="info">
                {COUNT_LABELS[key] ?? key} {value}
              </Badge>
            ))}
          </div>
          {memoryError ? (
            <div className="mb-3">
              <ErrorNote>
                PowerContext 记忆读取失败，本周报只包含 seekdb 中的资料与实验记录：{memoryError}
              </ErrorNote>
            </div>
          ) : null}
          {editing ? (
            <Textarea
              rows={26}
              value={markdown}
              onChange={(event) => setMarkdown(event.target.value)}
              className="font-mono text-xs"
              aria-label="周报 Markdown 源码"
            />
          ) : (
            <div className="rounded-lg border border-ink-700/70 bg-ink-950/50 p-4">
              <Markdown content={markdown} />
            </div>
          )}
        </Card>
      ) : (
        <EmptyState
          icon={<FileText className="h-6 w-6" />}
          title="还没有生成周报"
          description="选择时间区间后点击「生成周报」。系统会读取该区间内导入的资料、创建的实验记录（含指标与失败原因）以及 PowerContext 中的决策与进展。"
        />
      )}
    </div>
  )
}

const COUNT_LABELS: Record<string, string> = {
  documents: '新增资料',
  experiments: '实验记录',
  decisions: '研究决策',
  failures: '失败记录',
  next_actions: '下一步',
}

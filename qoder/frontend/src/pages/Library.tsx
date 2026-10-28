import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BookOpen,
  FileText,
  Layers,
  Search,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { api, type Chunk, type SearchMode, type SearchResponse } from '@/lib/api'
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
} from '@/components/ui/primitives'
import { Modal } from '@/components/ui/Modal'
import { formatDate } from '@/lib/utils'

const ACCEPTED = ['.pdf', '.md', '.markdown', '.txt']
const MAX_MB_FALLBACK = 20

export function Library() {
  const { currentProject } = useApp()
  const projectId = currentProject?.project_id ?? null
  const toast = useToast()
  const [topic, setTopic] = useState<string>('')
  const [uploadOpen, setUploadOpen] = useState(false)
  const [chunksFor, setChunksFor] = useState<{ docId: string; title: string } | null>(null)

  const [mode, setMode] = useState<SearchMode>('hybrid')
  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [openCitation, setOpenCitation] = useState<number | null>(null)

  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: 300_000 })
  const maxMb = Number(meta.data?.max_upload_mb ?? MAX_MB_FALLBACK)

  const documents = useQuery({
    queryKey: ['documents', projectId, topic],
    queryFn: () => api.listDocuments(projectId!, topic || undefined),
    enabled: Boolean(projectId),
  })

  const runSearch = async () => {
    if (!projectId || !query.trim()) return
    setSearching(true)
    setSearchError(null)
    setOpenCitation(null)
    try {
      setResult(await api.search({ project_id: projectId, query: query.trim(), mode, limit: 8 }))
    } catch (error) {
      setSearchError((error as Error).message)
      setResult(null)
    } finally {
      setSearching(false)
    }
  }

  const remove = async (docId: string, title: string) => {
    if (!projectId) return
    if (!window.confirm(`删除资料「${title}」？该文档在 seekdb 中的分块与向量索引会一并删除，操作不可撤销。`)) return
    try {
      await api.deleteDocument(docId, projectId)
      toast.push(`已删除「${title}」及其全部索引分块`, 'success')
      documents.refetch()
    } catch (error) {
      toast.push(`删除失败：${(error as Error).message}`, 'error')
    }
  }

  const topics = useMemo(() => documents.data?.topics ?? [], [documents.data])
  const rows = useMemo(() => documents.data?.documents ?? [], [documents.data])

  if (!currentProject) {
    return <EmptyState icon={<BookOpen className="h-8 w-8" />} title="请先选择研究项目" description="论文知识库按项目隔离，所有检索都限定在当前项目的 seekdb 数据分区内。" />
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="知识库检索"
          subtitle="检索请求实时发往 OceanBase seekdb：全文索引 MATCH…AGAINST、向量 ANN l2_distance APPROXIMATE，混合模式用 RRF 融合排序"
          action={
            <Button size="sm" variant="secondary" icon={<Upload className="h-3.5 w-3.5" />} onClick={() => setUploadOpen(true)}>
              上传资料
            </Button>
          }
        />
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[280px] flex-1">
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void runSearch()
              }}
              placeholder="例如：3D 场景记忆如何提升长时序问答准确率"
              aria-label="检索问题"
            />
          </div>
          <Select value={mode} onChange={(event) => setMode(event.target.value as SearchMode)} aria-label="检索模式" className="w-40">
            <option value="hybrid">混合检索</option>
            <option value="keyword">关键词（全文索引）</option>
            <option value="vector">向量（语义相似）</option>
          </Select>
          <Button onClick={runSearch} loading={searching} disabled={!query.trim()} icon={<Search className="h-4 w-4" />}>
            检索
          </Button>
        </div>

        {result ? (
          <div className="lt-muted mt-3 flex flex-wrap items-center gap-2 text-[11px]">
            <Badge tone="accent">{result.mode}</Badge>
            <span>{result.engine}</span>
            <span className="text-ink-600">·</span>
            <span className="font-mono">{result.sql_mode}</span>
            <span className="text-ink-600">·</span>
            <span>命中 {result.total} 个分块</span>
          </div>
        ) : null}
        {searchError ? <div className="mt-3"><ErrorNote>{searchError}</ErrorNote></div> : null}
      </Card>

      {result ? (
        <Card>
          <CardHeader title="检索结果与可点击引用" subtitle="每条引用都来自 seekdb 的真实记录，包含论文名称、页码与被引用的原文段落" />
          {result.citations.length === 0 ? (
            <EmptyState
              icon={<Search className="h-6 w-6" />}
              title="seekdb 中没有匹配的证据"
              description="这说明当前项目资料无法支撑该问题。系统不会编造论文内容，请调整关键词、上传相关资料，或改用混合检索。"
            />
          ) : (
            <ul className="space-y-2">
              {result.citations.map((citation, index) => {
                const open = openCitation === index
                return (
                  <li key={citation.chunk_id ?? index} className="rounded-lg border border-ink-700/70 bg-ink-900/50">
                    <button
                      onClick={() => setOpenCitation(open ? null : index)}
                      className="flex w-full items-start justify-between gap-3 px-3 py-2.5 text-left transition hover:bg-ink-800/50"
                    >
                      <span className="min-w-0">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="rounded bg-accent-500/20 px-1.5 py-0.5 font-mono text-[10px] text-accent-300">[{index + 1}]</span>
                          <span className="truncate text-xs font-medium text-ink-100">{citation.title ?? '未知资料'}</span>
                          <Badge tone="info">{citation.location ?? '未标注页码'}</Badge>
                          {citation.topic ? <Badge>{citation.topic}</Badge> : null}
                          {citation.matched_by ? <Badge tone="neutral">{String(citation.matched_by)}</Badge> : null}
                        </span>
                        <span className="lt-muted mt-1 block truncate text-[11px]">{citation.excerpt}</span>
                      </span>
                      <span className="shrink-0 text-right">
                        {typeof citation.score === 'number' ? (
                          <span className="lt-muted block font-mono text-[10px]">{citation.score.toFixed(4)}</span>
                        ) : null}
                      </span>
                    </button>
                    {open ? (
                      <div className="animate-fade-in border-t border-ink-700/70 px-3 py-3">
                        <p className="lt-label mb-1.5">被引用的原文段落</p>
                        <p className="whitespace-pre-wrap text-xs leading-relaxed text-ink-200">{citation.excerpt}</p>
                        <p className="lt-muted mt-2 font-mono text-[10px]">
                          chunk_id={citation.chunk_id} · doc_id={citation.doc_id} · page_no={citation.page_no ?? 'null'}
                        </p>
                      </div>
                    ) : null}
                  </li>
                )
              })}
            </ul>
          )}
        </Card>
      ) : null}

      <Card>
        <CardHeader
          title={`资料列表（${rows.length}）`}
          subtitle="PyMuPDF 逐页抽取文本，按段落切块并保留页码"
          action={
            topics.length > 0 ? (
              <Select value={topic} onChange={(event) => setTopic(event.target.value)} className="w-44" aria-label="按主题筛选">
                <option value="">全部主题</option>
                {topics.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </Select>
            ) : null
          }
        />
        {documents.isLoading ? (
          <div className="flex items-center gap-2 py-3 text-xs text-ink-400">
            <Spinner className="h-3.5 w-3.5" /> 正在从 seekdb 读取…
          </div>
        ) : documents.error ? (
          <ErrorNote>{(documents.error as Error).message}</ErrorNote>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<FileText className="h-6 w-6" />}
            title={topic ? `主题「${topic}」下没有资料` : '还没有导入任何资料'}
            description="支持 PDF、Markdown 与 TXT。上传后文件内容会被切块、生成向量，并写入 seekdb 的全文索引与向量索引。"
            action={<Button size="sm" variant="secondary" onClick={() => setUploadOpen(true)}>上传第一份资料</Button>}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="lt-label border-b border-ink-700/70">
                  <th className="py-2 pr-3 font-medium">标题</th>
                  <th className="py-2 pr-3 font-medium">主题</th>
                  <th className="py-2 pr-3 font-medium">类型</th>
                  <th className="py-2 pr-3 font-medium">页 / 分块</th>
                  <th className="py-2 pr-3 font-medium">导入时间</th>
                  <th className="py-2 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-800/70">
                {rows.map((doc) => (
                  <tr key={doc.doc_id} className="transition hover:bg-ink-900/50">
                    <td className="max-w-[280px] py-2.5 pr-3">
                      <p className="truncate font-medium text-ink-100">{doc.title}</p>
                      <p className="lt-muted truncate text-[11px]">{doc.file_name ?? doc.doc_id}</p>
                    </td>
                    <td className="py-2.5 pr-3">{doc.topic ? <Badge>{doc.topic}</Badge> : <span className="lt-muted">—</span>}</td>
                    <td className="py-2.5 pr-3 uppercase text-ink-300">{doc.file_type}</td>
                    <td className="py-2.5 pr-3 text-ink-300">
                      {doc.page_count || '—'} / {doc.chunk_count}
                    </td>
                    <td className="lt-muted py-2.5 pr-3">{formatDate(doc.created_at)}</td>
                    <td className="py-2.5">
                      <div className="flex justify-end gap-1">
                        <Button size="sm" variant="ghost" icon={<Layers className="h-3.5 w-3.5" />} onClick={() => setChunksFor({ docId: doc.doc_id, title: doc.title })}>
                          分块
                        </Button>
                        <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5 text-rose-400" />} onClick={() => remove(doc.doc_id, doc.title)} aria-label={`删除 ${doc.title}`} />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <UploadModal
        open={uploadOpen}
        projectId={projectId}
        maxMb={maxMb}
        onClose={() => setUploadOpen(false)}
        onDone={() => {
          setUploadOpen(false)
          documents.refetch()
        }}
      />

      <ChunksModal projectId={projectId} target={chunksFor} onClose={() => setChunksFor(null)} />
    </div>
  )
}

function UploadModal({
  open,
  projectId,
  maxMb,
  onClose,
  onDone,
}: {
  open: boolean
  projectId: string | null
  maxMb: number
  onClose: () => void
  onDone: () => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const toast = useToast()
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [topic, setTopic] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reset = () => {
    setFile(null)
    setTitle('')
    setTopic('')
    setError(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  const pick = (picked: File | null) => {
    setError(null)
    if (!picked) {
      setFile(null)
      return
    }
    const lower = picked.name.toLowerCase()
    if (!ACCEPTED.some((ext) => lower.endsWith(ext))) {
      setError(`不支持的文件类型：${picked.name}。仅允许 ${ACCEPTED.join(' / ')}`)
      setFile(null)
      return
    }
    if (picked.size > maxMb * 1024 * 1024) {
      setError(`文件超过上限 ${(picked.size / 1024 / 1024).toFixed(1)} MB > ${maxMb} MB`)
      setFile(null)
      return
    }
    if (picked.size === 0) {
      setError('文件为空，无法抽取内容')
      setFile(null)
      return
    }
    setFile(picked)
    if (!title) setTitle(picked.name.replace(/\.[^.]+$/, ''))
  }

  const submit = async () => {
    if (!file || !projectId) return
    setBusy(true)
    setError(null)
    const form = new FormData()
    form.append('project_id', projectId)
    form.append('file', file)
    if (title.trim()) form.append('title', title.trim())
    if (topic.trim()) form.append('topic', topic.trim())
    try {
      const result = (await api.uploadDocument(form)) as {
        doc_id?: string
        chunk_count?: number
        page_count?: number
        char_count?: number
        embedding_provider?: string
      }
      toast.push(
        `已导入「${title.trim() || file.name}」：${result.chunk_count ?? 0} 个分块写入 seekdb（向量维度来自 ${result.embedding_provider ?? '嵌入服务'}）`,
        'success',
      )
      reset()
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
      onClose={() => {
        reset()
        onClose()
      }}
      title="上传论文或研究笔记"
      description={`允许 ${ACCEPTED.join(' / ')}，单文件不超过 ${maxMb} MB。文件只在服务端解析，不落盘保存原文之外的副本。`}
      footer={
        <>
          <Button variant="ghost" disabled={busy} onClick={() => { reset(); onClose() }}>取消</Button>
          <Button loading={busy} disabled={!file || !title.trim()} onClick={submit}>导入并建立索引</Button>
        </>
      }
    >
      <div className="space-y-4">
        <div>
          <span className="lt-label mb-1.5 block">文件</span>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED.join(',')}
            onChange={(event) => pick(event.target.files?.[0] ?? null)}
            className="lt-input block w-full cursor-pointer text-xs file:mr-3 file:rounded-md file:border-0 file:bg-ink-700 file:px-3 file:py-1.5 file:text-xs file:text-ink-100"
          />
          {file ? (
            <p className="lt-muted mt-1.5 flex items-center gap-1.5 text-[11px]">
              <FileText className="h-3 w-3" /> {file.name} · {(file.size / 1024).toFixed(1)} KB
            </p>
          ) : null}
        </div>
        <Input label="标题" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="用于引用展示，默认取文件名" />
        <Input label="主题标签" value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="例如：3D Scene Memory（可选，用于筛选与召回加权）" />
        {error ? <ErrorNote>{error}</ErrorNote> : null}
      </div>
    </Modal>
  )
}

function ChunksModal({
  projectId,
  target,
  onClose,
}: {
  projectId: string | null
  target: { docId: string; title: string } | null
  onClose: () => void
}) {
  const chunks = useQuery({
    queryKey: ['chunks', target?.docId, projectId],
    queryFn: () => api.documentChunks(target!.docId, projectId!),
    enabled: Boolean(target && projectId),
  })
  const rows: Chunk[] = chunks.data?.chunks ?? []

  return (
    <Modal
      open={Boolean(target)}
      onClose={onClose}
      title="seekdb 中的分块"
      description={target ? `${target.title} · 共 ${chunks.data?.total ?? 0} 块，每块保存原文与页码，并带有向量与全文索引` : undefined}
      size="xl"
      footer={<Button variant="ghost" onClick={onClose} icon={<X className="h-3.5 w-3.5" />}>关闭</Button>}
    >
      {chunks.isLoading ? (
        <div className="flex items-center gap-2 py-3 text-xs text-ink-400">
          <Spinner className="h-3.5 w-3.5" /> 读取分块…
        </div>
      ) : chunks.error ? (
        <ErrorNote>{(chunks.error as Error).message}</ErrorNote>
      ) : rows.length === 0 ? (
        <EmptyState title="没有分块" />
      ) : (
        <ul className="space-y-2">
          {rows.map((chunk) => (
            <li key={chunk.chunk_id} className="rounded-lg border border-ink-700/70 bg-ink-900/50 px-3 py-2">
              <div className="mb-1 flex items-center gap-2">
                <Badge tone="info">#{chunk.chunk_index}</Badge>
                <Badge>{chunk.page_no ? `第 ${chunk.page_no} 页` : '全文'}</Badge>
                <span className="lt-muted ml-auto font-mono text-[10px]">{chunk.content.length} 字符</span>
              </div>
              <p className="whitespace-pre-wrap text-xs leading-relaxed text-ink-200">{chunk.content}</p>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  )
}

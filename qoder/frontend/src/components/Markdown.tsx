import { Fragment, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** Minimal, dependency-free Markdown renderer for assistant answers and reports. */
export function Markdown({ content, className }: { content: string; className?: string }) {
  return <div className={cn('space-y-2.5 text-sm leading-relaxed text-ink-200', className)}>{renderBlocks(content)}</div>
}

function renderBlocks(source: string): ReactNode[] {
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let index = 0
  let key = 0

  while (index < lines.length) {
    const line = lines[index]

    if (line.trim().startsWith('```')) {
      const buffer: string[] = []
      index += 1
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        buffer.push(lines[index])
        index += 1
      }
      index += 1
      blocks.push(
        <pre key={key++} className="overflow-x-auto rounded-lg border border-ink-700 bg-ink-950/70 p-3 font-mono text-xs text-ink-200">
          {buffer.join('\n')}
        </pre>,
      )
      continue
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1].length
      const text = renderInline(heading[2])
      const sizes: Record<number, string> = {
        1: 'text-lg font-semibold text-ink-50 mt-2',
        2: 'text-base font-semibold text-ink-50 mt-2',
        3: 'text-sm font-semibold text-ink-100 mt-1.5',
        4: 'text-xs font-semibold uppercase tracking-wide text-ink-300 mt-1.5',
      }
      blocks.push(
        <p key={key++} className={sizes[level] ?? sizes[3]}>
          {text}
        </p>,
      )
      index += 1
      continue
    }

    if (/^\s*[-*]\s+/.test(line)) {
      const items: ReactNode[] = []
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(<li key={items.length} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent-400" /><span>{renderInline(lines[index].replace(/^\s*[-*]\s+/, ''))}</span></li>)
        index += 1
      }
      blocks.push(<ul key={key++} className="space-y-1.5 pl-1">{items}</ul>)
      continue
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items: ReactNode[] = []
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        const text = lines[index].replace(/^\s*\d+\.\s+/, '')
        items.push(<li key={items.length} className="flex gap-2"><span className="font-mono text-xs text-accent-300">{items.length + 1}.</span><span>{renderInline(text)}</span></li>)
        index += 1
      }
      blocks.push(<ol key={key++} className="space-y-1.5 pl-1">{items}</ol>)
      continue
    }

    if (/^\s*(---|>\s)/.test(line) && line.trim() === '---') {
      blocks.push(<hr key={key++} className="border-ink-700/70" />)
      index += 1
      continue
    }

    if (!line.trim()) {
      index += 1
      continue
    }

    const paragraph: string[] = []
    while (index < lines.length && lines[index].trim() && !/^(#{1,4}\s|\s*[-*]\s|\s*\d+\.\s|```)/.test(lines[index])) {
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push(<p key={key++} className="whitespace-pre-wrap">{renderInline(paragraph.join('\n'))}</p>)
  }

  return blocks
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|\[\d+\])/g
  let cursor = 0
  let match: RegExpExecArray | null
  let key = 0

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(<Fragment key={key++}>{text.slice(cursor, match.index)}</Fragment>)
    const token = match[0]
    if (token.startsWith('**')) {
      nodes.push(<strong key={key++} className="font-semibold text-ink-50">{token.slice(2, -2)}</strong>)
    } else if (token.startsWith('`')) {
      nodes.push(<code key={key++} className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-[0.8em] text-accent-300">{token.slice(1, -1)}</code>)
    } else if (/^\[\d+\]$/.test(token)) {
      nodes.push(<span key={key++} className="mx-0.5 rounded bg-accent-500/20 px-1.5 py-0.5 font-mono text-[0.7em] text-accent-300">{token.slice(1, -1)}</span>)
    } else {
      const link = /\[([^\]]+)\]\(([^)]+)\)/.exec(token)
      if (link) {
        nodes.push(
          <a key={key++} href={link[2]} target="_blank" rel="noreferrer" className="text-accent-300 underline underline-offset-2 hover:text-accent-400">
            {link[1]}
          </a>,
        )
      }
    }
    cursor = match.index + token.length
  }
  if (cursor < text.length) nodes.push(<Fragment key={key++}>{text.slice(cursor)}</Fragment>)
  return nodes
}

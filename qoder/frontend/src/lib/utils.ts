import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatDay(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString('zh-CN')
}

export function truncate(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max)}…` : value
}

export const STATUS_LABELS: Record<string, string> = {
  planned: '计划中',
  running: '进行中',
  completed: '已完成',
  failed: '失败',
  abandoned: '已放弃',
}

export const STATUS_STYLES: Record<string, string> = {
  planned: 'bg-ink-700/60 text-ink-200',
  running: 'bg-sky-500/15 text-sky-300',
  completed: 'bg-emerald-500/15 text-emerald-300',
  failed: 'bg-rose-500/15 text-rose-300',
  abandoned: 'bg-amber-500/15 text-amber-300',
}

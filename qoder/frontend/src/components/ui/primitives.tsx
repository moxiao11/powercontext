import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md' | 'lg'

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-accent-600 text-white hover:bg-accent-500 active:bg-accent-700 shadow-glow disabled:bg-ink-700 disabled:text-ink-400 disabled:shadow-none',
  secondary:
    'bg-ink-800 text-ink-100 border border-ink-600 hover:bg-ink-700 hover:border-ink-500 disabled:opacity-50',
  ghost: 'text-ink-300 hover:text-ink-100 hover:bg-ink-800/70 disabled:opacity-50',
  danger: 'bg-rose-600/90 text-white hover:bg-rose-500 disabled:opacity-50',
}

const SIZES: Record<Size, string> = {
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-9 px-4 text-sm gap-2',
  lg: 'h-11 px-5 text-sm gap-2',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
}

export function Button({ variant = 'primary', size = 'md', loading, icon, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center rounded-lg font-medium transition-all duration-150',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50',
        'disabled:cursor-not-allowed',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <Spinner className="h-3.5 w-3.5" /> : icon}
      {children}
    </button>
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cn('animate-spin', className ?? 'h-4 w-4')} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-90" fill="currentColor" d="M4 12a8 8 0 018-8v3a5 5 0 00-5 5H4z" />
    </svg>
  )
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('lt-card p-5', className)}>{children}</div>
}

export function CardHeader({ title, subtitle, action }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-start justify-between gap-4">
      <div>
        <h3 className="text-sm font-semibold text-ink-100">{title}</h3>
        {subtitle ? <p className="lt-muted mt-1 text-xs">{subtitle}</p> : null}
      </div>
      {action}
    </div>
  )
}

export function Badge({ children, className, tone = 'neutral' }: { children: ReactNode; className?: string; tone?: 'neutral' | 'accent' | 'success' | 'warn' | 'danger' | 'info' }) {
  const tones = {
    neutral: 'bg-ink-800 text-ink-300 border-ink-700',
    accent: 'bg-accent-500/15 text-accent-300 border-accent-500/30',
    success: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    warn: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    danger: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
    info: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
  }
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium', tones[tone], className)}>
      {children}
    </span>
  )
}

export function Input({ className, label, hint, ...rest }: InputHTMLAttributes<HTMLInputElement> & { label?: string; hint?: string }) {
  return (
    <label className="block">
      {label ? <span className="lt-label mb-1.5 block">{label}</span> : null}
      <input className={cn('lt-input', className)} {...rest} />
      {hint ? <span className="lt-muted mt-1 block text-[11px]">{hint}</span> : null}
    </label>
  )
}

export function Textarea({ className, label, hint, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string; hint?: string }) {
  return (
    <label className="block">
      {label ? <span className="lt-label mb-1.5 block">{label}</span> : null}
      <textarea className={cn('lt-input resize-y leading-relaxed', className)} {...rest} />
      {hint ? <span className="lt-muted mt-1 block text-[11px]">{hint}</span> : null}
    </label>
  )
}

export function Select({ className, label, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  return (
    <label className="block">
      {label ? <span className="lt-label mb-1.5 block">{label}</span> : null}
      <select className={cn('lt-input appearance-none pr-8', className)} {...rest}>
        {children}
      </select>
    </label>
  )
}

export function EmptyState({ icon, title, description, action }: { icon?: ReactNode; title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-ink-700 px-6 py-14 text-center">
      {icon ? <div className="mb-3 text-ink-500">{icon}</div> : null}
      <p className="text-sm font-medium text-ink-200">{title}</p>
      {description ? <p className="lt-muted mt-1.5 max-w-md text-xs leading-relaxed">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  )
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
      {children}
    </div>
  )
}

export function SectionTitle({ children, className }: { children: ReactNode; className?: string }) {
  return <h2 className={cn('text-base font-semibold text-ink-100', className)}>{children}</h2>
}

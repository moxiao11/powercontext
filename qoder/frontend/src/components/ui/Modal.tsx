import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ModalProps {
  open: boolean
  title: string
  description?: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  size?: 'md' | 'lg' | 'xl'
}

export function Modal({ open, title, description, onClose, children, footer, size = 'md' }: ModalProps) {
  useEffect(() => {
    if (!open) return
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null
  const widths = { md: 'max-w-lg', lg: 'max-w-2xl', xl: 'max-w-4xl' }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink-950/80 p-4 backdrop-blur-sm sm:items-center">
      <div className={cn('lt-card animate-fade-in w-full p-0', widths[size])}>
        <div className="flex items-start justify-between gap-4 border-b border-ink-700/70 px-5 py-4">
          <div>
            <h3 className="text-sm font-semibold text-ink-100">{title}</h3>
            {description ? <p className="lt-muted mt-1 text-xs">{description}</p> : null}
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-ink-400 transition hover:bg-ink-800 hover:text-ink-100"
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer ? <div className="flex justify-end gap-2 border-t border-ink-700/70 px-5 py-3">{footer}</div> : null}
      </div>
    </div>
  )
}

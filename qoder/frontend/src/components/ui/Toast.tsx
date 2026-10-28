import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react'
import { cn } from '@/lib/utils'

type ToastTone = 'success' | 'error' | 'info'

interface Toast {
  id: number
  tone: ToastTone
  message: string
}

interface ToastContextValue {
  push: (message: string, tone?: ToastTone) => void
}

const ToastContext = createContext<ToastContextValue>({ push: () => {} })

export function useToast() {
  return useContext(ToastContext)
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback((message: string, tone: ToastTone = 'info') => {
    const id = Date.now() + Math.random()
    setToasts((current) => [...current, { id, tone, message }])
    window.setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), 5200)
  }, [])

  const value = useMemo(() => ({ push }), [push])
  const icons = {
    success: <CheckCircle2 className="h-4 w-4 text-emerald-400" />,
    error: <AlertTriangle className="h-4 w-4 text-rose-400" />,
    info: <Info className="h-4 w-4 text-sky-400" />,
  }

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[60] flex w-80 flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              'lt-card animate-fade-in pointer-events-auto flex items-start gap-2.5 p-3 text-xs',
              toast.tone === 'error' && 'border-rose-500/40',
              toast.tone === 'success' && 'border-emerald-500/30',
            )}
          >
            {icons[toast.tone]}
            <span className="flex-1 leading-relaxed text-ink-200">{toast.message}</span>
            <button
              onClick={() => setToasts((current) => current.filter((item) => item.id !== toast.id))}
              className="text-ink-500 transition hover:text-ink-200"
              aria-label="关闭提示"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type HealthResponse, type Project } from '@/lib/api'

interface AppState {
  theme: 'dark' | 'light'
  toggleTheme: () => void
  projects: Project[]
  projectsLoading: boolean
  projectsError: string | null
  currentProject: Project | null
  setCurrentProjectId: (id: string | null) => void
  currentProjectId: string | null
  health: HealthResponse | null
  healthLoading: boolean
  refreshProjects: () => void
}

const AppContext = createContext<AppState | null>(null)

const PROJECT_KEY = 'labtrace.currentProjectId'
const THEME_KEY = 'labtrace.theme'

export function AppProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => (localStorage.getItem(THEME_KEY) as 'dark' | 'light') || 'dark')
  const [currentProjectId, setCurrentProjectIdState] = useState<string | null>(() => localStorage.getItem(PROJECT_KEY))

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle('dark', theme === 'dark')
    root.classList.toggle('light', theme === 'light')
    localStorage.setItem(THEME_KEY, theme)
  }, [theme])

  const projectsQuery = useQuery({
    queryKey: ['projects'],
    queryFn: async () => (await api.listProjects()).projects,
    staleTime: 20_000,
  })

  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 30_000,
    retry: 1,
  })

  const projects = projectsQuery.data ?? []

  useEffect(() => {
    if (!currentProjectId && projects.length > 0) {
      setCurrentProjectIdState(projects[0].project_id)
    }
    if (currentProjectId && projects.length > 0 && !projects.some((p) => p.project_id === currentProjectId)) {
      setCurrentProjectIdState(projects[0].project_id)
    }
  }, [projects, currentProjectId])

  const setCurrentProjectId = useCallback((id: string | null) => {
    setCurrentProjectIdState(id)
    if (id) localStorage.setItem(PROJECT_KEY, id)
    else localStorage.removeItem(PROJECT_KEY)
  }, [])

  const value = useMemo<AppState>(
    () => ({
      theme,
      toggleTheme: () => setTheme((current) => (current === 'dark' ? 'light' : 'dark')),
      projects,
      projectsLoading: projectsQuery.isLoading,
      projectsError: projectsQuery.error ? (projectsQuery.error as Error).message : null,
      currentProject: projects.find((p) => p.project_id === currentProjectId) ?? null,
      currentProjectId,
      setCurrentProjectId,
      health: healthQuery.data ?? null,
      healthLoading: healthQuery.isLoading,
      refreshProjects: () => projectsQuery.refetch(),
    }),
    [theme, projects, projectsQuery, currentProjectId, setCurrentProjectId, healthQuery],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const context = useContext(AppContext)
  if (!context) throw new Error('useApp must be used inside AppProvider')
  return context
}

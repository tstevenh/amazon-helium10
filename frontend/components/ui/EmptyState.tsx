import type { ReactNode } from 'react'

interface EmptyStateProps {
  title?: string
  description?: string
  action?: ReactNode
}
export function EmptyState({ title = 'No results', description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center gap-3">
      <svg className="h-12 w-12 text-ink-faint" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
          d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0H4" />
      </svg>
      <div>
        <p className="text-sm font-medium text-ink">{title}</p>
        {description && <p className="text-sm text-ink-muted mt-1">{description}</p>}
      </div>
      {action}
    </div>
  )
}

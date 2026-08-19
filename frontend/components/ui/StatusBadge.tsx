import type { ReactNode } from 'react'

const STATUS_STYLES: Record<string, string> = {
  enabled:       'bg-ok-tint text-ok',
  active:        'bg-ok-tint text-ok',
  connected:     'bg-ok-tint text-ok',
  paused:        'bg-warn-tint text-warn',
  archived:      'bg-surface-sunken  text-ink-muted',
  disabled:      'bg-surface-sunken  text-ink-muted',
  auth_required: 'bg-danger-tint   text-danger',
  not_connected: 'bg-danger-tint   text-danger',
}

export function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status.toLowerCase()] ?? 'bg-surface-sunken text-ink-muted'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium capitalize ${cls}`}>
      {status}
    </span>
  )
}

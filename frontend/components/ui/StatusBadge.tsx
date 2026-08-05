import type { ReactNode } from 'react'

const STATUS_STYLES: Record<string, string> = {
  enabled:       'bg-green-100 text-green-800',
  active:        'bg-green-100 text-green-800',
  connected:     'bg-green-100 text-green-800',
  paused:        'bg-yellow-100 text-yellow-800',
  archived:      'bg-gray-100  text-gray-600',
  disabled:      'bg-gray-100  text-gray-600',
  auth_required: 'bg-red-100   text-red-700',
  not_connected: 'bg-red-100   text-red-700',
}

export function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status.toLowerCase()] ?? 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium capitalize ${cls}`}>
      {status}
    </span>
  )
}

'use client'
/**
 * Logs — what actually changed on Amazon, and how to undo it.
 *
 * The spec calls this "non-negotiable for trust in automation. Must answer
 * 'why did this bid change' instantly." Every row is a confirmed change: the
 * backend only writes change_log after Amazon has accepted a write, so a row
 * here never describes something that did not happen.
 *
 * The Undo button writes to Amazon. It is deliberately behind a confirmation
 * that names the actual values — a dialog nobody reads is not a safeguard.
 */
import { useCallback, useEffect, useState } from 'react'

import { DataTable, type Column } from '@/components/ui/DataTable'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { useAuth } from '@/context/AuthContext'
import { ApiError, api } from '@/lib/api'
import type { ChangeLogEntry } from '@/lib/types'

const SOURCE_LABEL: Record<string, string> = {
  suggestion_execution: 'Suggestion',
  manual_edit: 'Manual',
  rollback: 'Rollback',
}

const SOURCE_STYLE: Record<string, string> = {
  suggestion_execution: 'bg-info-tint text-accent',
  manual_edit: 'bg-surface-sunken text-ink',
  rollback: 'bg-warn-tint text-warn',
}

function fmtWhen(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

export default function LogsPage() {
  const { user } = useAuth()
  const { currentProfileId, profiles } = useAccountProfile()

  const [rows, setRows] = useState<ChangeLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.getChangeLog(currentProfileId ?? undefined)
      setRows(res.changes)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not load the change log')
    } finally {
      setLoading(false)
    }
  }, [currentProfileId])

  useEffect(() => { if (user) load() }, [user, load])

  const handleUndo = async (row: ChangeLogEntry) => {
    // Name the real values. "Are you sure?" teaches people to click through.
    const ok = window.confirm(
      `Restore ${row.field_changed} from ${row.new_value} back to ${row.old_value} on Amazon?\n\n` +
      `This writes to your live ad account.`,
    )
    if (!ok) return

    setBusyId(row.id)
    setToast(null)
    try {
      const res = await api.rollbackChange(row.id)
      setToast(res.ok ? `Undone — ${res.detail}` : `Could not undo: ${res.detail}`)
      await load()
    } catch (e) {
      setToast(e instanceof ApiError ? `Could not undo: ${e.message}` : 'Could not undo')
    } finally {
      setBusyId(null)
    }
  }

  const marketplaceOf = (profileId: string) =>
    profiles.find(p => p.id === profileId)?.country_code ?? '—'

  const columns: Column<ChangeLogEntry>[] = [
    {
      header: 'When',
      cell: r => <span className="text-ink-muted text-xs">{fmtWhen(r.changed_at)}</span>,
      sortValue: r => r.changed_at ?? '',
    },
    {
      header: 'Marketplace',
      cell: r => <span className="text-ink-muted">{marketplaceOf(r.profile_id)}</span>,
    },
    {
      header: 'What',
      cell: r => (
        <span className="text-ink">
          {r.entity_type} <span className="text-ink-subtle">·</span> {r.field_changed}
        </span>
      ),
    },
    {
      header: 'Change',
      cell: r => (
        <span className="font-mono text-sm">
          <span className="text-ink-muted line-through">{r.old_value ?? '—'}</span>
          <span className="mx-1.5 text-ink-subtle">→</span>
          <span className="text-ink font-medium">{r.new_value ?? '—'}</span>
        </span>
      ),
    },
    {
      header: 'Source',
      cell: r => (
        <span className={`px-2 py-0.5 rounded text-xs ${SOURCE_STYLE[r.source] ?? 'bg-surface-sunken text-ink'}`}>
          {SOURCE_LABEL[r.source] ?? r.source}
        </span>
      ),
      sortValue: r => r.source,
    },
    {
      header: 'Amazon ID',
      cell: r => <span className="text-ink-subtle text-xs font-mono">{r.amazon_entity_id ?? '—'}</span>,
    },
    {
      header: '',
      cell: r => {
        if (r.rolled_back_at) {
          return (
            <span className="text-xs text-ink-subtle" title={fmtWhen(r.rolled_back_at)}>
              undone
            </span>
          )
        }
        if (r.source === 'rollback') {
          // Undoing an undo would oscillate the value; the backend refuses it.
          return <span className="text-xs text-ink-faint">—</span>
        }
        return (
          <button
            onClick={() => handleUndo(r)}
            disabled={busyId === r.id}
            className="text-xs px-2 py-1 rounded border border-line hover:bg-surface-sunken disabled:opacity-50"
          >
            {busyId === r.id ? 'Undoing…' : 'Undo'}
          </button>
        )
      },
    },
  ]

  if (error) return <ErrorState message={error} onRetry={load} />

  return (
    <div className="p-8">
      <div className="mb-6">
        <h1 className="text-xl font-semibold tracking-tight text-ink">Change Log</h1>
        <p className="text-sm text-ink-muted mt-1">
          {rows.length} change{rows.length === 1 ? '' : 's'} written to Amazon
          {currentProfileId ? '' : ' across all marketplaces'}
        </p>
      </div>

      {toast && (
        <div className="mb-4 px-4 py-2 rounded bg-surface-sunken text-sm text-ink">
          {toast}
        </div>
      )}

      <div className="bg-surface rounded-lg border border-hairline">
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={r => r.id}
          loading={loading}
          emptyTitle="No changes yet"
          emptyDescription={
            'Nothing has been written to Amazon yet. Changes appear here once an ' +
            'approved suggestion is executed.'
          }
        />
      </div>
    </div>
  )
}

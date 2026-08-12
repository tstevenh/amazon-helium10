'use client'
/**
 * Sync Monitor.
 *
 * The health data existed for a week before this screen did, and in that week
 * eight scheduled syncs failed without anyone noticing — the failures were
 * only discoverable by querying sync_jobs by hand. A webhook covers the case
 * where someone configured one; this covers the case where nobody did.
 */
import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { api, ApiError } from '@/lib/api'
import type { SyncJobRow } from '@/lib/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/ui/LoadingState'
import { ErrorState } from '@/components/ui/ErrorState'

const STATUS_STYLE: Record<string, string> = {
  success: 'bg-green-100 text-green-700',
  partial: 'bg-yellow-100 text-yellow-800',
  failed:  'bg-red-100 text-red-700',
  running: 'bg-blue-100 text-blue-700',
  queued:  'bg-gray-100 text-gray-600',
}

/** Plain-English cause, so a non-engineer can tell "our fault" from "Amazon's". */
function explainError(msg: string | null): string | null {
  if (!msg) return null
  if (msg.includes('NameResolutionError') || msg.includes('Max retries exceeded')) {
    return 'No internet connection when the sync ran — the machine was probably asleep or off Wi-Fi.'
  }
  if (msg.includes('token refresh failed')) {
    return 'Could not renew the Amazon login. Usually a network problem; if it repeats, reconnect the account.'
  }
  if (msg.includes('429') || msg.toLowerCase().includes('throttl')) {
    return 'Amazon rate-limited the request. It normally clears on the next run.'
  }
  if (msg.includes('502') || msg.includes('503')) {
    return 'Amazon returned a server error. Their side, not yours.'
  }
  return null
}

function fmtTime(s: string | null) {
  return s ? new Date(s).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }) : '—'
}

function fmtDuration(start: string | null, end: string | null) {
  if (!start || !end) return '—'
  const ms = new Date(end).getTime() - new Date(start).getTime()
  const min = Math.floor(ms / 60000)
  if (min < 1) return `${Math.round(ms / 1000)}s`
  return min < 60 ? `${min}m` : `${Math.floor(min / 60)}h ${min % 60}m`
}

export default function SyncMonitorPage() {
  const { user, loading: authLoading } = useAuth()
  const router = useRouter()

  const [jobs, setJobs]         = useState<SyncJobRow[]>([])
  const [staleHours, setStale]  = useState(24)
  const [scheduleHours, setSch] = useState(6)
  const [loading, setLoading]   = useState(false)
  const [error, setError]       = useState<string | null>(null)

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const page = await api.listSyncJobs({ limit: 50 })
      setJobs(page.jobs)
      setStale(page.stale_after_hours)
      setSch(page.schedule_hours)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load sync history')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (user) load() }, [user, load])

  // Refresh while something is in flight so the screen doesn't lie about it.
  const hasActive = jobs.some(j => j.status === 'running' || j.status === 'queued')
  useEffect(() => {
    if (!hasActive) return
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [hasActive, load])

  const stats = useMemo(() => {
    const week = jobs.filter(j => {
      if (!j.created_at) return false
      return Date.now() - new Date(j.created_at).getTime() < 7 * 24 * 3600 * 1000
    })
    const lastSuccess = jobs.find(j => j.status === 'success' && j.finished_at)
    const hoursSince = lastSuccess?.finished_at
      ? (Date.now() - new Date(lastSuccess.finished_at).getTime()) / 3600000
      : null
    return {
      success: week.filter(j => j.status === 'success').length,
      partial: week.filter(j => j.status === 'partial').length,
      failed:  week.filter(j => j.status === 'failed').length,
      hoursSince,
      isStale: hoursSince == null || hoursSince > staleHours,
    }
  }, [jobs, staleHours])

  if (authLoading) return <LoadingState message="Loading…" />
  if (!user) return null
  if (error) return <ErrorState message={error} onRetry={load} />

  return (
    <div className="space-y-4">
      <PageHeader
        title="Sync Monitor"
        subtitle={`Automatic sync runs every ${scheduleHours} hours. Data is considered stale after ${staleHours}.`}
      />

      {/* Headline: is the data current? Everything else is detail. */}
      <div className={`rounded-xl border p-4 ${
        stats.isStale ? 'border-red-200 bg-red-50' : 'border-green-200 bg-green-50'
      }`}>
        <p className={`text-sm font-semibold ${stats.isStale ? 'text-red-800' : 'text-green-800'}`}>
          {stats.isStale ? '⚠ Data may be out of date' : '✓ Data is current'}
        </p>
        <p className={`text-sm mt-0.5 ${stats.isStale ? 'text-red-700' : 'text-green-700'}`}>
          {stats.hoursSince == null
            ? 'No sync has ever completed successfully.'
            : `Last successful sync ${stats.hoursSince < 1
                ? 'less than an hour ago'
                : `${Math.floor(stats.hoursSince)} hours ago`}.`}
        </p>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Succeeded (7d)', value: stats.success, cls: 'border-green-200 bg-white' },
          { label: 'Partial (7d)',   value: stats.partial, cls: 'border-yellow-200 bg-white' },
          { label: 'Failed (7d)',    value: stats.failed,  cls: 'border-red-200 bg-white' },
        ].map(s => (
          <div key={s.label} className={`rounded-xl border p-4 ${s.cls}`}>
            <p className="text-xs text-gray-500">{s.label}</p>
            <p className="text-2xl font-bold text-gray-900 mt-1">{s.value}</p>
          </div>
        ))}
      </div>

      <p className="text-xs text-gray-500">
        <span className="font-medium">Partial</span> means the sync ran but Amazon
        returned an incomplete picture — the data it did fetch was kept, and nothing
        was deleted.
      </p>

      <div className="card p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 w-24">Status</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 w-28">Type</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 w-40">Started</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 w-24">Duration</th>
              <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600 w-28">Records</th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Result</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading && jobs.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-12 text-center text-gray-400">Loading…</td></tr>
            ) : jobs.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-12 text-center text-gray-400">
                No syncs recorded yet. Run one from Settings → Accounts.
              </td></tr>
            ) : jobs.map(j => {
              const plain = explainError(j.error_message)
              return (
                <tr key={j.id} className="hover:bg-gray-50 align-top">
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${STATUS_STYLE[j.status] ?? 'bg-gray-100 text-gray-600'}`}>
                      {j.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs font-mono">{j.job_type}</td>
                  <td className="px-4 py-3 text-gray-600 text-xs">{fmtTime(j.started_at ?? j.created_at)}</td>
                  <td className="px-4 py-3 text-gray-600 text-xs">{fmtDuration(j.started_at, j.finished_at)}</td>
                  <td className="px-4 py-3 text-right text-gray-800">
                    {j.records_synced ? j.records_synced.toLocaleString() : '—'}
                  </td>
                  <td className="px-4 py-3">
                    {j.error_message ? (
                      <>
                        {plain && <p className="text-xs text-gray-800 mb-1">{plain}</p>}
                        <details>
                          <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600">
                            Technical detail
                          </summary>
                          <p className="text-xs text-red-600 mt-1 font-mono break-all">{j.error_message}</p>
                        </details>
                      </>
                    ) : j.status === 'running' ? (
                      <span className="text-xs text-blue-600">In progress…</span>
                    ) : (
                      <span className="text-xs text-gray-400">—</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

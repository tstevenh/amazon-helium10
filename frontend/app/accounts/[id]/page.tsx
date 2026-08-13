'use client'
import { useEffect, useState, useCallback } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { api, ApiError } from '@/lib/api'
import type { AccountDetail, ConnectionTestResponse, Profile, SyncJob, SyncResult, SyncStatus } from '@/lib/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, Column } from '@/components/ui/DataTable'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'

function fmt(ts: string | null | undefined): string {
  if (!ts) return 'Never'
  return new Date(ts).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function ModeBadge({ mode }: { mode: 'mock' | 'real' | undefined }) {
  if (mode === 'real') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
        <span className="w-1.5 h-1.5 rounded-full bg-green-500 inline-block" />
        Real Mode
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
      <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 inline-block" />
      Mock Mode
    </span>
  )
}

const STEP_LABELS: Record<string, string> = {
  credentials_stored: 'Credentials stored',
  token_decrypt:      'Token decrypt',
  token_refresh:      'Token refresh',
  profiles_api:       'Profiles API',
}

function ConnectionTestPanel({ accountId, onClose }: { accountId: string; onClose: () => void }) {
  const [loading, setLoading] = useState(true)
  const [result, setResult] = useState<ConnectionTestResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const run = useCallback(async () => {
    setLoading(true)
    setErr(null)
    setResult(null)
    try {
      const r = await api.connectionTest(accountId)
      setResult(r)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Connection test failed')
    } finally {
      setLoading(false)
    }
  }, [accountId])

  useEffect(() => { run() }, [run])

  const allPassed = result?.steps.every(s => s.passed) ?? false

  return (
    <div className="card mb-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-gray-700">Connection Diagnostic</h2>
        <div className="flex items-center gap-3">
          <button onClick={run} disabled={loading} className="text-xs text-blue-600 hover:underline disabled:opacity-40">
            {loading ? 'Running…' : 'Re-run'}
          </button>
          <button onClick={onClose} className="text-xs text-gray-400 hover:text-gray-600">✕</button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <svg className="animate-spin h-4 w-4 text-blue-500" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
          </svg>
          Running diagnostic…
        </div>
      )}

      {err && <p className="text-sm text-red-600">{err}</p>}

      {result && !loading && (
        <>
          <div className={`rounded-lg px-4 py-3 mb-4 text-sm font-medium ${
            allPassed
              ? 'bg-green-50 text-green-800 border border-green-200'
              : 'bg-red-50 text-red-800 border border-red-200'
          }`}>
            {allPassed
              ? `✓ All checks passed — ${result.profile_count} profile${result.profile_count !== 1 ? 's' : ''} found`
              : `✗ ${result.error ?? 'One or more checks failed'}`
            }
          </div>

          <div className="flex items-center gap-4 mb-4 text-xs text-gray-500">
            <ModeBadge mode={result.mode} />
            <span>{result.profile_count} profile{result.profile_count !== 1 ? 's' : ''} visible to this token</span>
          </div>

          <div className="space-y-2">
            {result.steps.map(step => (
              <div key={step.name} className={`flex items-start gap-3 p-3 rounded-lg border ${
                step.passed ? 'border-green-100 bg-green-50' : 'border-red-100 bg-red-50'
              }`}>
                <span className={`mt-0.5 text-base ${step.passed ? 'text-green-600' : 'text-red-500'}`}>
                  {step.passed ? '✓' : '✗'}
                </span>
                <div className="min-w-0 flex-1">
                  <p className={`text-xs font-semibold ${step.passed ? 'text-green-800' : 'text-red-800'}`}>
                    {STEP_LABELS[step.name] ?? step.name}
                  </p>
                  <p className={`text-xs mt-0.5 break-words ${step.passed ? 'text-green-700' : 'text-red-700'}`}>
                    {step.detail}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// ── Sync section ───────────────────────────────────────────────────────────

interface SyncResults {
  campaigns?: SyncResult
  ad_groups?: SyncResult
  targets?: SyncResult
  lastAt?: string
}

function SyncResultChip({ label, result }: { label: string; result: SyncResult }) {
  return (
    <div className={`rounded-lg border px-3 py-2 ${result.partial ? 'border-yellow-300 bg-yellow-50' : 'border-gray-100 bg-gray-50'}`}>
      <p className="text-xs font-semibold text-gray-600 mb-1">{label}</p>
      <p className="text-xs text-gray-500">
        <span className="text-green-700 font-medium">{result.upserted}</span> synced
        {result.soft_deleted > 0 && (
          <span className="ml-2 text-gray-400">{result.soft_deleted} removed</span>
        )}
        {result.pages_fetched != null && result.pages_fetched > 0 && (
          <span className="ml-2 text-gray-400">{result.pages_fetched}p / {result.rows_fetched?.toLocaleString()}r</span>
        )}
      </p>
      {result.partial && (
        <p className="text-[10px] text-yellow-700 mt-1">⚠ Partial — set AMAZON_FULL_SYNC_MAX_PAGES=0 for full sync</p>
      )}
    </div>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function AccountDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { user, loading: authLoading } = useAuth()
  const { refreshProfiles } = useAccountProfile()
  const router = useRouter()

  const [account, setAccount] = useState<AccountDetail | null>(null)
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [dataLoading, setDataLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [syncMsg, setSyncMsg] = useState<string | null>(null)
  const [showTest, setShowTest] = useState(false)
  const [connectedBanner, setConnectedBanner] = useState(false)

  // Sync state — isSyncing tracks whether syncAll is in flight
  const [isSyncing, setIsSyncing] = useState(false)
  const [syncResults, setSyncResults] = useState<SyncResults>({})
  const [syncError, setSyncError] = useState<string | null>(null)
  // undefined = routine rolling window (3 days, or 90 on a first sync).
  // A number forces that many days — 90 is a slow deliberate backfill.
  const [syncDays, setSyncDays] = useState<number | undefined>(undefined)
  // DB counts loaded from /sync-status on mount — persists across navigations
  const [dbStatus, setDbStatus] = useState<SyncStatus | null>(null)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('connected') === 'true') {
      setConnectedBanner(true)
      window.history.replaceState({}, '', window.location.pathname)
      const t = setTimeout(() => setConnectedBanner(false), 6000)
      return () => clearTimeout(t)
    }
  }, [])

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async () => {
    setDataLoading(true)
    setError(null)
    try {
      const [acc, profs] = await Promise.all([
        api.getAccount(id),
        api.getProfiles(id),
      ])
      setAccount(acc)
      setProfiles(profs)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load account')
    } finally {
      setDataLoading(false)
    }
  }, [id])

  const loadSyncStatus = useCallback(async () => {
    try {
      const status = await api.getSyncStatus(id)
      setDbStatus(status)
      // Resume polling if page is refreshed while a sync is running
      if (status.sync_job?.running && !isSyncing) {
        setIsSyncing(true)
      }
    } catch {
      // Non-fatal: status panel just won't show counts
    }
  }, [id, isSyncing])

  useEffect(() => {
    if (user) {
      load()
      loadSyncStatus()
    }
  }, [user, load, loadSyncStatus])

  // Poll sync-status every 3 s while a sync is in flight
  useEffect(() => {
    if (!isSyncing) return
    let active = true

    const poll = setInterval(async () => {
      try {
        const status = await api.getSyncStatus(id)
        if (!active) return
        setDbStatus(status)
        const job: SyncJob | undefined = status.sync_job
        if (job && !job.running) {
          setIsSyncing(false)
          if (job.error) {
            setSyncError(job.error)
          } else if (job.result) {
            const r = job.result as Record<string, unknown>
            setSyncResults({
              campaigns: r.campaigns as SyncResult,
              ad_groups: r.ad_groups as SyncResult,
              targets:   r.targets   as SyncResult,
              lastAt: new Date().toISOString(),
            })
          }
        }
      } catch {
        // Polling error — keep retrying
      }
    }, 3000)

    return () => {
      active = false
      clearInterval(poll)
    }
  }, [isSyncing, id])

  if (authLoading) return <LoadingState message="Checking authentication…" />
  if (!user) return null
  if (error) return <ErrorState message={error} onRetry={load} />
  if (dataLoading) return <LoadingState />
  if (!account) return null

  const cred = account.credential_status
  const mode = cred?.mode ?? 'mock'
  const lastSyncedAt = cred?.last_synced_at ??
    profiles.map(p => p.last_synced_at).filter(Boolean).sort().at(-1) ?? null

  const handleRefresh = async () => {
    setSyncing(true)
    setSyncMsg(null)
    try {
      const result = await api.syncProfiles(id)
      setSyncMsg(`Refreshed ${result.profiles_synced} profile${result.profiles_synced !== 1 ? 's' : ''}`)
      await load()
      await refreshProfiles()
    } catch (e) {
      setSyncMsg(e instanceof ApiError ? e.message : 'Refresh failed')
    } finally {
      setSyncing(false)
    }
  }

  const handleConnect = async () => {
    setConnecting(true)
    setSyncMsg(null)
    try {
      const result = await api.oauthStart(id)
      window.location.href = result.auth_url
    } catch (e) {
      setSyncMsg(e instanceof ApiError ? e.message : 'Failed to start OAuth')
      setConnecting(false)
    }
  }

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await api.deleteAccount(id)
      window.location.href = '/accounts'
    } catch (e) {
      setSyncMsg(e instanceof ApiError ? e.message : 'Delete failed')
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  /**
   * Fire-and-forget sync: POST returns 202 immediately.
   * We set isSyncing=true and let the polling useEffect track progress
   * via GET /sync-status until sync_job.running becomes false.
   */
  const handleSyncAll = async () => {
    setSyncError(null)
    setSyncResults({})
    setIsSyncing(true)
    try {
      await api.syncAll(id, syncDays) // 202 — backend is running in background thread
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // Already running — that's fine, just keep polling
      } else {
        setSyncError(e instanceof ApiError ? e.message : 'Sync failed — check Amazon connection')
        setIsSyncing(false)
      }
    }
  }

  const profileColumns: Column<Profile>[] = [
    {
      header: 'Marketplace',
      cell: row => <span className="font-medium">{row.country_code ?? '—'}</span>,
      sortValue: row => row.country_code ?? '',
    },
    {
      header: 'Currency',
      cell: row => <span className="text-gray-600">{row.currency_code ?? '—'}</span>,
    },
    {
      header: 'Timezone',
      cell: row => <span className="text-gray-600 text-xs">{row.timezone ?? '—'}</span>,
    },
    {
      header: 'Status',
      cell: row => <StatusBadge status={row.status} />,
    },
    {
      header: 'Last Synced',
      cell: row => <span className="text-gray-500 text-xs">{fmt(row.last_synced_at)}</span>,
      sortValue: row => row.last_synced_at ?? '',
    },
    {
      header: 'Marketplace ID',
      cell: row => <span className="text-gray-400 text-xs font-mono">{row.marketplace_code}</span>,
    },
  ]

  return (
    <div>
      <button onClick={() => router.back()} className="text-sm text-blue-600 hover:underline mb-4 inline-block">
        ← Back to Accounts
      </button>

      {connectedBanner && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg flex items-center justify-between">
          <span className="text-green-800 text-sm font-medium">
            ✅ Amazon Ads connected successfully! {profiles.length} profile{profiles.length !== 1 ? 's' : ''} synced.
          </span>
          <button onClick={() => setConnectedBanner(false)} className="text-green-600 hover:text-green-800 text-xs">✕</button>
        </div>
      )}

      <PageHeader
        title={account.name}
        subtitle={`${profiles.length} profile${profiles.length !== 1 ? 's' : ''}`}
        actions={
          <div className="flex items-center gap-3">
            {syncMsg && <span className="text-sm text-gray-600 max-w-xs">{syncMsg}</span>}
            <button onClick={() => setShowTest(t => !t)} className="btn-secondary text-sm">
              {showTest ? 'Hide Diagnostic' : 'Run Connection Test'}
            </button>
            <button onClick={handleRefresh} disabled={syncing} className="btn-secondary">
              {syncing ? 'Refreshing…' : 'Refresh Profiles'}
            </button>
          </div>
        }
      />

      {/* Status card */}
      <div className="card mb-6">
        <div className="flex flex-wrap items-center gap-6">
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Mode</p>
            <ModeBadge mode={mode} />
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Amazon Connection</p>
            <StatusBadge status={cred?.connected ? 'connected' : 'not_connected'} />
          </div>
          {cred?.token_expires_at && (
            <div title="Amazon access tokens last ~1 hour. The system auto-refreshes using the stored refresh token.">
              <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Token Expires</p>
              <span className="text-sm text-gray-700">{fmt(cred.token_expires_at)}</span>
            </div>
          )}
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">Last Profile Sync</p>
            <span className="text-sm text-gray-700">{fmt(lastSyncedAt)}</span>
          </div>
          <button
            onClick={handleConnect}
            disabled={connecting}
            className="btn-primary text-sm disabled:opacity-50"
          >
            {connecting ? 'Redirecting to Amazon…' : cred?.connected ? 'Re-connect Amazon Ads' : 'Connect Amazon Ads'}
          </button>
        </div>
      </div>

      {showTest && (
        <ConnectionTestPanel accountId={id} onClose={() => setShowTest(false)} />
      )}

      {/* Profiles table */}
      <div className="card mb-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Profiles</h2>
        <DataTable
          columns={profileColumns}
          rows={profiles}
          rowKey={r => r.id}
          emptyTitle="No profiles"
          emptyDescription={
            mode === 'mock'
              ? 'Click Bootstrap Demo Data on the Accounts page to load mock data.'
              : 'Click "Connect Amazon Ads" to start OAuth, then Refresh Profiles.'
          }
        />
      </div>

      {/* Campaign Data Sync */}
      <div className="card mb-6">
        <div className="flex items-center justify-between mb-1">
          <h2 className="text-sm font-semibold text-gray-700">Campaign Data Sync</h2>
        </div>

        {/* Persistent DB status — loaded on mount, survives navigation */}
        {dbStatus && (dbStatus.campaigns.count > 0 || dbStatus.targets.count > 0) ? (
          <div className="mb-4 rounded-lg bg-gray-50 border border-gray-100 px-4 py-3">
            <div className="flex flex-wrap items-center gap-4 text-xs text-gray-600">
              <span>
                <span className="font-semibold text-gray-800">{dbStatus.campaigns.count.toLocaleString()}</span> campaigns
              </span>
              <span className="text-gray-300">·</span>
              <span>
                <span className="font-semibold text-gray-800">{dbStatus.ad_groups.count.toLocaleString()}</span> ad groups
              </span>
              <span className="text-gray-300">·</span>
              <span>
                <span className="font-semibold text-gray-800">{dbStatus.targets.count.toLocaleString()}</span> targets in database
              </span>
              {dbStatus.campaigns.last_synced_at && (
                <>
                  <span className="text-gray-300">·</span>
                  <span className="text-gray-400">Last synced: {fmt(dbStatus.campaigns.last_synced_at)}</span>
                </>
              )}
            </div>
          </div>
        ) : (
          <p className="text-xs text-gray-400 mb-4">
            Pulls all campaigns, ad groups, and keywords from Amazon Ads into the database.
          </p>
        )}

        {/* Progress banner */}
        {isSyncing && (
          <div className="mb-4 p-3 bg-blue-50 border border-blue-200 rounded-lg">
            <div className="flex items-center gap-2 text-sm text-blue-800">
              <svg className="animate-spin h-4 w-4 text-blue-500 flex-shrink-0" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
              </svg>
              <span className="font-medium">Syncing all data from Amazon Ads… (live counts update below)</span>
            </div>
            {/* This used to promise "2–4 minutes", which was true when a sync
                only fetched campaign lists. Performance data now comes from
                Amazon reports, and Amazon builds each one on its own schedule —
                measured at 23–40 minutes per report on a real account. Anyone
                watching an honest hour-long sync against a 4-minute estimate
                reasonably concludes it has hung. */}
            <p className="text-xs text-blue-600 mt-1 ml-6">
              Campaigns, ad groups and keywords land within a few minutes; the counts
              above update as they arrive. Performance history is much slower — Amazon
              builds each report on its own schedule, around 20–40 minutes each, so a
              30-day pull often takes about an hour and 90 days can take several. This
              is normal, not a stall. Safe to navigate away; the sync runs in the
              background. Detailed progress is on Sync Monitor.
            </p>
          </div>
        )}

        {syncError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            {syncError}
          </div>
        )}

        <div className="mb-3 flex items-center gap-2 text-sm">
          <span className="text-gray-500">Performance history:</span>
          {([
            { label: 'Routine', value: undefined, hint: 'Last 3 days — fast, keeps recent numbers fresh' },
            { label: '7 days',  value: 7,  hint: 'About 15 minutes' },
            { label: '30 days', value: 30, hint: 'About an hour' },
            { label: '90 days', value: 90, hint: 'Full backfill — several hours' },
          ] as const).map(opt => (
            <button
              key={opt.label}
              type="button"
              title={opt.hint}
              onClick={() => setSyncDays(opt.value)}
              disabled={isSyncing}
              className={`px-2.5 py-1 rounded border text-xs transition-colors disabled:opacity-50 ${
                syncDays === opt.value
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'
              }`}
            >
              {opt.label}
            </button>
          ))}
          {syncDays === 90 && (
            <span className="text-xs text-amber-600">
              90 days is ~18 Amazon reports and can take several hours.
            </span>
          )}
        </div>

        <button
          onClick={handleSyncAll}
          disabled={isSyncing}
          className="w-full px-4 py-3 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isSyncing ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
              </svg>
              Syncing…
            </span>
          ) : 'Sync All'}
        </button>

        {/* Result chips — all three appear together when syncAll completes */}
        {(syncResults.campaigns || syncResults.ad_groups || syncResults.targets) && (
          <div className="grid grid-cols-3 gap-3 mt-4">
            {syncResults.campaigns && (
              <SyncResultChip label="Campaigns" result={syncResults.campaigns} />
            )}
            {syncResults.ad_groups && (
              <SyncResultChip label="Ad Groups" result={syncResults.ad_groups} />
            )}
            {syncResults.targets && (
              <SyncResultChip label="Targets" result={syncResults.targets} />
            )}
          </div>
        )}
      </div>

      {/* Danger zone */}
      <div className="card border border-red-200">
        <h2 className="text-sm font-semibold text-red-700 mb-3">Danger Zone</h2>
        {!confirmDelete ? (
          <button
            onClick={() => setConfirmDelete(true)}
            className="px-4 py-2 bg-white border border-red-300 text-red-600 text-sm rounded hover:bg-red-50"
          >
            Delete Account
          </button>
        ) : (
          <div className="flex items-center gap-3">
            <span className="text-sm text-red-700">
              Delete <strong>{account.name}</strong> and all its profiles/credentials? This cannot be undone.
            </span>
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="px-4 py-2 bg-red-600 text-white text-sm rounded hover:bg-red-700 disabled:opacity-50"
            >
              {deleting ? 'Deleting…' : 'Yes, Delete'}
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="px-3 py-2 text-sm text-gray-500 hover:text-gray-700"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

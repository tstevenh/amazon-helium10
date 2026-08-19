'use client'
import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { api, ApiError } from '@/lib/api'
import type { Account } from '@/lib/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, Column } from '@/components/ui/DataTable'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { SearchBox } from '@/components/ui/SearchBox'
import { LoadingState } from '@/components/ui/LoadingState'
import { ErrorState } from '@/components/ui/ErrorState'

function ModeBadge({ mode }: { mode: 'mock' | 'real' | undefined }) {
  if (mode === 'real') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
        <span className="w-1.5 h-1.5 rounded-full bg-green-500 inline-block" />
        Real
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
      <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 inline-block" />
      Mock
    </span>
  )
}

// ── Inline "New Account" form ─────────────────────────────────────────────
function NewAccountForm({ onCreated, onCancel }: {
  onCreated: (id: string) => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    setErr(null)
    try {
      const account = await api.createAccount(name.trim())
      onCreated(account.id)
    } catch (e) {
      console.error('[PPC-OS createAccount error]', e)
      const msg = e instanceof ApiError ? e.message
        : (e instanceof Error ? `${e.constructor.name}: ${e.message}` : String(e))
      setErr(msg)
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-center gap-3 p-3 bg-blue-50 border border-blue-200 rounded-lg mb-4">
      <input
        autoFocus
        type="text"
        value={name}
        onChange={e => setName(e.target.value)}
        placeholder="Account name (e.g. My Amazon Store)"
        className="flex-1 px-3 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        disabled={saving}
      />
      <button
        type="submit"
        disabled={saving || !name.trim()}
        className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
      >
        {saving ? 'Creating…' : 'Create Account'}
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700"
      >
        Cancel
      </button>
      {err && <span className="text-xs text-red-600">{err}</span>}
    </form>
  )
}

export default function AccountsPage() {
  const { user, loading: authLoading } = useAuth()
  const router = useRouter()

  const [accounts, setAccounts] = useState<Account[]>([])
  const [search, setSearch] = useState('')
  const [dataLoading, setDataLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [bootstrapping, setBootstrapping] = useState(false)
  const [bootstrapMsg, setBootstrapMsg] = useState<string | null>(null)
  const [showNewForm, setShowNewForm] = useState(false)
  // oauth_error is set when backend redirects here after a failed OAuth flow
  const [oauthError, setOauthError] = useState<string | null>(null)

  // Read ?oauth_error from URL client-side (avoids useSearchParams / Suspense issues)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const err = params.get('oauth_error')
    if (err) {
      setOauthError(decodeURIComponent(err))
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [])

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async () => {
    setDataLoading(true)
    setError(null)
    try {
      const data = await api.listAccounts()
      setAccounts(data)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load accounts')
    } finally {
      setDataLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!authLoading && user) load()
  }, [authLoading, user, load])

  const handleBootstrap = useCallback(async () => {
    setBootstrapping(true)
    setBootstrapMsg(null)
    try {
      const result = await api.bootstrapDemoData()
      const r = result as Record<string, unknown>
      setBootstrapMsg(
        `✅ Bootstrap complete — ${r.profiles_synced} profiles, ` +
        `${r.campaigns_upserted} campaigns, ` +
        `${r.search_terms_synced} search terms, ` +
        `${r.suggestions_generated} suggestions`
      )
      await load()
    } catch (e) {
      setBootstrapMsg(`❌ ${e instanceof ApiError ? e.message : 'Bootstrap failed'}`)
    } finally {
      setBootstrapping(false)
    }
  }, [load])

  if (authLoading) return <LoadingState message="Checking authentication…" />
  if (!user) return null

  // Only determine mode after data loaded — prevents Mock Mode flash
  const globalMode = dataLoading ? null : (accounts[0]?.credential_status?.mode ?? 'mock')
  const isRealMode = globalMode === 'real'

  const filtered = accounts.filter(a =>
    a.name.toLowerCase().includes(search.toLowerCase())
  )

  const columns: Column<Account>[] = [
    {
      header: 'Name',
      cell: row => <span className="font-medium text-gray-900">{row.name}</span>,
      sortValue: row => row.name,
    },
    {
      header: 'Mode',
      cell: row => <ModeBadge mode={row.credential_status?.mode} />,
    },
    {
      header: 'Profiles',
      cell: row => <span className="text-gray-600">{row.profile_count ?? 0}</span>,
      sortValue: row => row.profile_count ?? 0,
    },
    {
      header: 'Amazon Connection',
      cell: row => (
        <StatusBadge
          status={row.credential_status?.connected ? 'connected' : 'not_connected'}
        />
      ),
    },
    {
      header: 'Last Sync',
      cell: row => (
        <span className="text-gray-500 text-xs">
          {row.credential_status?.last_synced_at
            ? new Date(row.credential_status.last_synced_at).toLocaleString(undefined, {
                dateStyle: 'short',
                timeStyle: 'short',
              })
            : '—'}
        </span>
      ),
      sortValue: row => row.credential_status?.last_synced_at ?? '',
    },
    {
      header: 'Created',
      cell: row => (
        <span className="text-gray-500 text-xs">
          {new Date(row.created_at).toLocaleDateString()}
        </span>
      ),
      sortValue: row => row.created_at,
    },
  ]

  if (error) return <ErrorState message={error} onRetry={load} />

  return (
    <div>
      <PageHeader
        title="Seller Accounts"
        subtitle={`${accounts.length} account${accounts.length !== 1 ? 's' : ''}`}
        actions={
          <button
            onClick={() => setShowNewForm(f => !f)}
            className="btn-primary text-sm"
          >
            {showNewForm ? 'Cancel' : '+ New Account'}
          </button>
        }
      />

      {/* OAuth error banner */}
      {oauthError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center justify-between">
          <span className="text-red-800 text-sm">❌ Amazon connection failed: {oauthError}</span>
          <button onClick={() => setOauthError(null)} className="text-red-400 hover:text-red-600 text-xs ml-4">✕</button>
        </div>
      )}

      {/* New account inline form */}
      {showNewForm && (
        <NewAccountForm
          onCreated={(id) => {
            setShowNewForm(false)
            // Use hard navigation to guarantee the detail page renders fresh
            window.location.href = `/accounts/${id}`
          }}
          onCancel={() => setShowNewForm(false)}
        />
      )}

      {/* Mode banner — only render after data loads to prevent flash */}
      {!dataLoading && (
        isRealMode ? (
          <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg flex items-center gap-3">
            <span className="text-green-800 text-sm font-medium">
              🟢 Real Mode — connecting to live Amazon Ads API
            </span>
            <span className="text-green-700 text-xs">
              AMAZON_MOCK_MODE=false · Open any account and click "Run Connection Test" to verify
            </span>
          </div>
        ) : (
          <div className="mb-4 p-3 bg-yellow-50 border border-yellow-200 rounded-lg flex items-center gap-3">
            <span className="text-yellow-800 text-sm font-medium">🛠 Mock Mode</span>
            <button
              onClick={handleBootstrap}
              disabled={bootstrapping}
              className="px-3 py-1.5 bg-yellow-600 text-white text-sm rounded hover:bg-yellow-700 disabled:opacity-50"
            >
              {bootstrapping ? 'Bootstrapping…' : 'Bootstrap Demo Data'}
            </button>
            {bootstrapMsg && (
              <span className="text-sm text-yellow-900">{bootstrapMsg}</span>
            )}
          </div>
        )
      )}

      <div className="card">
        <div className="mb-4">
          <SearchBox value={search} onChange={setSearch} placeholder="Search accounts…" />
        </div>
        <DataTable
          columns={columns}
          rows={filtered}
          rowKey={r => r.id}
          onRowClick={r => router.push(`/accounts/${r.id}`)}
          rowHref={r => `/accounts/${r.id}`}
          resizeKey="accounts"
          loading={dataLoading}
          emptyTitle="No accounts"
          emptyDescription={
            isRealMode
              ? 'Click "+ New Account" to create your first seller account, then connect Amazon Ads via OAuth.'
              : 'Click Bootstrap Demo Data above to load mock data.'
          }
        />
      </div>
    </div>
  )
}

'use client'
import { useEffect, useState, useMemo, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { api, ApiError } from '@/lib/api'
import { Suggestion } from '@/lib/types'

// ── helpers ───────────────────────────────────────────────────────────────────

function fmtCurrency(s: string | number | null | undefined) {
  if (s == null) return '—'
  const v = typeof s === 'number' ? s : parseFloat(String(s))
  return isNaN(v) ? '—' : '$' + v.toFixed(2)
}

function fmtPct(s: string | null | undefined) {
  if (!s) return '—'
  const v = parseFloat(s)
  return isNaN(v) ? '—' : (v * 100).toFixed(1) + '%'
}

function fmtDate(s: string) {
  return new Date(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

const TYPE_LABELS: Record<string, string> = {
  negative_exact:  'Neg Exact',
  negative_phrase: 'Neg Phrase',
  keyword_exact:   'KW Exact',
  keyword_phrase:  'KW Phrase',
  keyword_broad:   'KW Broad',
  bid_decrease:    'Bid ↓',
  bid_increase:    'Bid ↑',
}

const TYPE_COLORS: Record<string, string> = {
  negative_exact:  'bg-red-100 text-red-700',
  negative_phrase: 'bg-orange-100 text-orange-700',
  keyword_exact:   'bg-green-100 text-green-700',
  keyword_phrase:  'bg-emerald-100 text-emerald-700',
  keyword_broad:   'bg-teal-100 text-teal-700',
  bid_decrease:    'bg-purple-100 text-purple-700',
  bid_increase:    'bg-blue-100 text-blue-700',
}

const STATUS_COLORS: Record<string, string> = {
  pending:  'bg-yellow-100 text-yellow-700',
  approved: 'bg-green-100 text-green-700',
  rejected: 'bg-gray-100 text-gray-500',
}

function confidenceBadge(score: number): string {
  if (score >= 80) return 'bg-emerald-100 text-emerald-700 font-semibold'
  if (score >= 50) return 'bg-yellow-100 text-yellow-700'
  return 'bg-gray-100 text-gray-500'
}

function confidenceBar(score: number): string {
  if (score >= 80) return 'bg-emerald-500'
  if (score >= 50) return 'bg-yellow-400'
  return 'bg-gray-300'
}

type SortBy = 'newest' | 'confidence' | 'spend' | 'sales'
type ConfidenceRange = 'all' | 'low' | 'med' | 'high'

// ── Detail Drawer ─────────────────────────────────────────────────────────────

function DetailDrawer({ s, onClose }: { s: Suggestion; onClose: () => void }) {
  const snap = s.metrics_snapshot
  // Close on Escape
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      {/* Panel */}
      <div className="relative w-full max-w-md bg-white shadow-xl flex flex-col overflow-y-auto">
        {/* Header */}
        <div className="flex items-start justify-between px-5 py-4 border-b border-gray-200 sticky top-0 bg-white z-10">
          <div className="flex-1 min-w-0 pr-3">
            <p className="text-xs text-gray-400 mb-1">Search Term</p>
            <h2 className="text-base font-semibold text-gray-900 break-words">{s.search_term}</h2>
          </div>
          <button onClick={onClose}
            className="text-gray-400 hover:text-gray-600 flex-shrink-0 text-xl leading-none mt-0.5">×</button>
        </div>

        {/* Badges row */}
        <div className="flex flex-wrap gap-2 px-5 py-3 border-b border-gray-100">
          <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${TYPE_COLORS[s.suggestion_type] ?? 'bg-gray-100 text-gray-600'}`}>
            {TYPE_LABELS[s.suggestion_type] ?? s.suggestion_type}
          </span>
          <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[s.status] ?? ''}`}>
            {s.status}
          </span>
          <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${confidenceBadge(s.confidence_score ?? 0)}`}>
            Confidence {s.confidence_score ?? 0}
          </span>
        </div>

        {/* Confidence bar */}
        <div className="px-5 py-3 border-b border-gray-100">
          <div className="flex items-center justify-between text-xs text-gray-500 mb-1.5">
            <span>Confidence Score</span>
            <span className="font-semibold text-gray-700">{s.confidence_score ?? 0} / 100</span>
          </div>
          <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${confidenceBar(s.confidence_score ?? 0)}`}
              style={{ width: `${s.confidence_score ?? 0}%` }}
            />
          </div>
        </div>

        {/* Reason */}
        <div className="px-5 py-3 border-b border-gray-100">
          <p className="text-xs text-gray-400 mb-1">Reason</p>
          <p className="text-sm text-gray-700">{s.reason}</p>
        </div>

        {/* Source — shown for rule-generated suggestions */}
        {s.source_type === 'rule' && s.source_rule_name && (
          <div className="px-5 py-3 border-b border-gray-100">
            <p className="text-xs text-gray-400 mb-1">Source</p>
            <div className="flex items-center gap-2">
              <span className="text-xs px-2 py-0.5 rounded bg-indigo-100 text-indigo-700 font-medium">
                ⚙️ Rule
              </span>
              <p className="text-sm text-gray-700">{s.source_rule_name}</p>
            </div>
          </div>
        )}

        {/* Coverage */}
        <div className="px-5 py-3 border-b border-gray-100">
          <p className="text-xs text-gray-400 mb-2">Coverage</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-gray-50 rounded-lg p-3">
              <p className="text-xs text-gray-500">Campaigns Affected</p>
              <p className="text-lg font-semibold text-gray-900 mt-0.5">{s.campaign_count ?? 1}</p>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <p className="text-xs text-gray-500">Ad Groups Affected</p>
              <p className="text-lg font-semibold text-gray-900 mt-0.5">{s.ad_group_count ?? 1}</p>
            </div>
          </div>
        </div>

        {/* Aggregated metrics */}
        <div className="px-5 py-3 border-b border-gray-100">
          <p className="text-xs text-gray-400 mb-2">Aggregated Metrics (30 days)</p>
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: 'Total Spend', value: fmtCurrency(s.total_spend) },
              { label: 'Total Sales', value: fmtCurrency(s.total_sales) },
              { label: 'Total Orders', value: String(s.total_orders ?? 0) },
              { label: 'Impressions', value: String(snap.impressions ?? 0) },
              { label: 'Clicks', value: String(snap.clicks ?? 0) },
              { label: 'ACOS', value: fmtPct(snap.acos) },
              { label: 'ROAS', value: snap.roas ? parseFloat(snap.roas).toFixed(2) + '×' : '—' },
              { label: 'CVR', value: fmtPct(snap.conversion_rate) },
              { label: 'CPC', value: snap.clicks ? fmtCurrency(String(parseFloat(String(snap.cost ?? 0)) / Math.max(snap.clicks, 1))) : '—' },
            ].map(({ label, value }) => (
              <div key={label} className="bg-gray-50 rounded-lg p-2.5">
                <p className="text-xs text-gray-400">{label}</p>
                <p className="text-sm font-medium text-gray-800 mt-0.5 truncate">{value}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Timeline */}
        <div className="px-5 py-3">
          <p className="text-xs text-gray-400 mb-2">Timeline</p>
          <div className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <span className="text-gray-500">Created</span>
              <span className="text-gray-700">{fmtDate(s.created_at)}</span>
            </div>
            {s.resolved_at && (
              <div className="flex justify-between">
                <span className="text-gray-500 capitalize">{s.status}</span>
                <span className="text-gray-700">{fmtDate(s.resolved_at)}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Metrics Summary Cards ─────────────────────────────────────────────────────

function SummaryCards({ suggestions }: { suggestions: Suggestion[] }) {
  const pending  = suggestions.filter(s => s.status === 'pending').length
  const approved = suggestions.filter(s => s.status === 'approved').length
  const rejected = suggestions.filter(s => s.status === 'rejected').length

  const spendSavings = suggestions
    .filter(s => s.kind === 'negative' && s.status === 'pending')
    .reduce((acc, s) => acc + parseFloat(String(s.total_spend || '0')), 0)

  const harvestOpps = suggestions.filter(s => s.kind === 'harvest' && s.status === 'pending').length

  const cards = [
    { label: 'Pending',               value: String(pending),               sub: 'awaiting review',       color: 'border-yellow-300 bg-yellow-50' },
    { label: 'Approved',              value: String(approved),              sub: 'actioned',               color: 'border-green-300 bg-green-50' },
    { label: 'Rejected',              value: String(rejected),              sub: 'dismissed',              color: 'border-gray-300 bg-gray-50' },
    { label: 'Potential Savings',     value: fmtCurrency(String(spendSavings)), sub: 'from pending negatives', color: 'border-red-300 bg-red-50' },
    { label: 'Harvest Opportunities', value: String(harvestOpps),           sub: 'pending keywords',       color: 'border-blue-300 bg-blue-50' },
  ]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      {cards.map(({ label, value, sub, color }) => (
        <div key={label} className={`rounded-xl border p-3.5 ${color}`}>
          <p className="text-xs text-gray-500 truncate">{label}</p>
          <p className="text-xl font-bold text-gray-900 mt-1 truncate">{value}</p>
          <p className="text-xs text-gray-400 mt-0.5 truncate">{sub}</p>
        </div>
      ))}
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function SuggestionsPage() {
  const router = useRouter()
  const { user, loading: authLoading } = useAuth()
  const {
    currentAccountId, currentProfileId, accountProfileIds,
    accountsLoading, profilesLoading,
  } = useAccountProfile()

  const [suggestions,  setSuggestions]  = useState<Suggestion[]>([])
  const [loading,      setLoading]      = useState(false)
  const [generating,   setGenerating]   = useState(false)
  const [error,        setError]        = useState<string | null>(null)
  const [genMsg,       setGenMsg]       = useState<string | null>(null)
  const [actionError,  setActionError]  = useState<string | null>(null)
  const [bulkMsg,      setBulkMsg]      = useState<string | null>(null)

  // filters
  const [statusTab,    setStatusTab]    = useState<string>('pending')
  const [kindTab,      setKindTab]      = useState<string>('all')
  const [confRange,    setConfRange]    = useState<ConfidenceRange>('all')
  const [sortBy,       setSortBy]       = useState<SortBy>('newest')
  const [search,       setSearch]       = useState('')

  // bulk selection
  const [selected,     setSelected]     = useState<Set<string>>(new Set())
  const [bulkActing,   setBulkActing]   = useState(false)

  // per-row inline action state
  const [actioning,    setActioning]    = useState<Record<string, boolean>>({})

  // detail drawer
  const [drawer,       setDrawer]       = useState<Suggestion | null>(null)

  // auth guard
  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const profileIds: string[] = useMemo(() => {
    if (currentProfileId) return [currentProfileId]
    return Array.from(accountProfileIds)
  }, [currentProfileId, accountProfileIds])

  const load = useCallback(async () => {
    // BUG-1 fix: wait for both accounts AND profiles to finish loading
    if (!profileIds.length || accountsLoading || profilesLoading) return
    setLoading(true)
    setError(null)
    setSelected(new Set())
    try {
      const all: Suggestion[] = []
      for (const pid of profileIds) {
        const data = await api.listSuggestions({ profile_id: pid })
        all.push(...data)
      }
      all.sort((a, b) => {
        if (a.status === 'pending' && b.status !== 'pending') return -1
        if (a.status !== 'pending' && b.status === 'pending') return 1
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      })
      setSuggestions(all)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load suggestions')
    } finally {
      setLoading(false)
    }
  }, [profileIds, accountsLoading, profilesLoading])

  // BUG-1 fix: include profilesLoading in deps so effect re-fires when context settles
  useEffect(() => {
    if (user && !accountsLoading && !profilesLoading && profileIds.length) load()
  }, [user, accountsLoading, profilesLoading, profileIds, load])

  async function handleGenerate() {
    if (!profileIds.length) return
    setGenerating(true)
    setGenMsg(null)
    setError(null)
    let total = 0
    try {
      for (const pid of profileIds) {
        const res = await api.generateSuggestions(pid)
        total += res.suggestions_generated
      }
      setGenMsg(`Generated ${total} new suggestion${total !== 1 ? 's' : ''}`)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Generate failed')
    } finally {
      setGenerating(false)
    }
  }

  async function handleApprove(id: string) {
    setActioning(a => ({ ...a, [id]: true }))
    setActionError(null)
    try {
      const updated = await api.approveSuggestion(id)
      setSuggestions(prev => prev.map(s => s.id === id ? updated : s))
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : 'Action failed')
    } finally {
      setActioning(a => ({ ...a, [id]: false }))
    }
  }

  async function handleReject(id: string) {
    setActioning(a => ({ ...a, [id]: true }))
    setActionError(null)
    try {
      const updated = await api.rejectSuggestion(id)
      setSuggestions(prev => prev.map(s => s.id === id ? updated : s))
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : 'Action failed')
    } finally {
      setActioning(a => ({ ...a, [id]: false }))
    }
  }

  // Bulk actions
  async function handleBulkApprove() {
    if (!selected.size) return
    setBulkActing(true)
    setBulkMsg(null)
    setActionError(null)
    try {
      const res = await api.bulkApproveSuggestions(Array.from(selected))
      setBulkMsg(`Approved ${res.resolved} suggestion${res.resolved !== 1 ? 's' : ''}${res.skipped ? ` (${res.skipped} skipped)` : ''}`)
      await load()
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : 'Bulk approve failed')
    } finally {
      setBulkActing(false)
    }
  }

  async function handleBulkReject() {
    if (!selected.size) return
    setBulkActing(true)
    setBulkMsg(null)
    setActionError(null)
    try {
      const res = await api.bulkRejectSuggestions(Array.from(selected))
      setBulkMsg(`Rejected ${res.resolved} suggestion${res.resolved !== 1 ? 's' : ''}${res.skipped ? ` (${res.skipped} skipped)` : ''}`)
      await load()
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : 'Bulk reject failed')
    } finally {
      setBulkActing(false)
    }
  }

  // Filtering
  const confBounds: [number, number] = confRange === 'low'  ? [0,  49]
                                     : confRange === 'med'  ? [50, 79]
                                     : confRange === 'high' ? [80, 100]
                                     : [0, 100]

  const filtered = useMemo(() => {
    let list = suggestions.filter(s => {
      if (statusTab !== 'all' && s.status !== statusTab) return false
      if (kindTab   !== 'all' && s.kind   !== kindTab)   return false
      if (confRange !== 'all') {
        const sc = s.confidence_score ?? 0
        if (sc < confBounds[0] || sc > confBounds[1]) return false
      }
      if (search && !s.search_term.toLowerCase().includes(search.toLowerCase()) &&
                    !s.reason.toLowerCase().includes(search.toLowerCase())) return false
      return true
    })

    // Sort
    if (sortBy === 'confidence') {
      list = [...list].sort((a, b) => (b.confidence_score ?? 0) - (a.confidence_score ?? 0))
    } else if (sortBy === 'spend') {
      list = [...list].sort((a, b) => parseFloat(String(b.total_spend || '0')) - parseFloat(String(a.total_spend || '0')))
    } else if (sortBy === 'sales') {
      list = [...list].sort((a, b) => parseFloat(String(b.total_sales || '0')) - parseFloat(String(a.total_sales || '0')))
    }
    // 'newest' — already sorted by default load order

    return list
  }, [suggestions, statusTab, kindTab, confRange, sortBy, search, confBounds])

  // Selection helpers
  const pendingFiltered = filtered.filter(s => s.status === 'pending')
  const allPageSelected = pendingFiltered.length > 0 && pendingFiltered.every(s => selected.has(s.id))

  function toggleAll() {
    if (allPageSelected) {
      setSelected(prev => {
        const next = new Set(prev)
        pendingFiltered.forEach(s => next.delete(s.id))
        return next
      })
    } else {
      setSelected(prev => {
        const next = new Set(prev)
        pendingFiltered.forEach(s => next.add(s.id))
        return next
      })
    }
  }

  function toggleRow(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const noContext  = !accountsLoading && !currentAccountId
  const noProfiles = !profilesLoading && currentAccountId && profileIds.length === 0

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Suggestion Inbox</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            AI-generated negative, harvest &amp; bid adjustment suggestions
          </p>
        </div>
        <button
          onClick={handleGenerate}
          disabled={generating || !profileIds.length}
          className="btn-secondary"
        >
          {generating ? 'Generating…' : '⚡ Generate Suggestions'}
        </button>
      </div>

      {/* Metrics Summary Cards */}
      {!noContext && !noProfiles && suggestions.length > 0 && (
        <SummaryCards suggestions={suggestions} />
      )}

      {/* Status messages */}
      {genMsg && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2 text-sm text-green-700">
          {genMsg}
        </div>
      )}
      {bulkMsg && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-2 text-sm text-blue-700">
          {bulkMsg}
        </div>
      )}
      {actionError && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2 text-sm text-red-700">
          {actionError}
        </div>
      )}

      {/* Filters */}
      {!noContext && !noProfiles && (
        <div className="flex flex-wrap gap-2 items-center">
          {/* Status */}
          <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
            {(['all', 'pending', 'approved', 'rejected'] as const).map(t => (
              <button key={t} onClick={() => setStatusTab(t)}
                className={`px-3 py-2 capitalize transition-colors ${
                  statusTab === t ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}>
                {t}{t === 'pending' ? ` (${suggestions.filter(s => s.status === 'pending').length})` : ''}
              </button>
            ))}
          </div>

          {/* Kind — includes 'bid' for Sprint 3 */}
          <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
            {(['all', 'negative', 'harvest', 'bid'] as const).map(k => (
              <button key={k} onClick={() => setKindTab(k)}
                className={`px-3 py-2 capitalize transition-colors ${
                  kindTab === k ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
                }`}>
                {k}
              </button>
            ))}
          </div>

          {/* Confidence range */}
          <select
            value={confRange}
            onChange={e => setConfRange(e.target.value as ConfidenceRange)}
            className="input text-sm py-2 pr-8"
          >
            <option value="all">All Confidence</option>
            <option value="low">Low (0–49)</option>
            <option value="med">Medium (50–79)</option>
            <option value="high">High (80–100)</option>
          </select>

          {/* Sort */}
          <select
            value={sortBy}
            onChange={e => setSortBy(e.target.value as SortBy)}
            className="input text-sm py-2 pr-8"
          >
            <option value="newest">Newest</option>
            <option value="confidence">Highest Confidence</option>
            <option value="spend">Highest Spend</option>
            <option value="sales">Highest Sales</option>
          </select>

          {/* Search */}
          <input type="search" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Filter by term or reason…"
            className="input text-sm flex-1 min-w-[180px]" />
        </div>
      )}

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 bg-blue-50 border border-blue-200 rounded-lg px-4 py-2.5">
          <span className="text-sm font-medium text-blue-800">
            {selected.size} selected
          </span>
          <button
            onClick={handleBulkApprove}
            disabled={bulkActing}
            className="text-xs px-3 py-1.5 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 transition-colors font-medium"
          >
            {bulkActing ? '…' : 'Approve Selected'}
          </button>
          <button
            onClick={handleBulkReject}
            disabled={bulkActing}
            className="text-xs px-3 py-1.5 bg-white border border-gray-300 text-gray-600 rounded hover:bg-gray-50 disabled:opacity-50 transition-colors"
          >
            {bulkActing ? '…' : 'Reject Selected'}
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="text-xs text-blue-600 hover:underline ml-auto"
          >
            Clear Selection
          </button>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {noContext && (
        <div className="card text-center py-12 text-gray-500">Select an account to view suggestions.</div>
      )}
      {noProfiles && (
        <div className="card text-center py-12 text-gray-500">
          No profiles synced. Go to Settings → Accounts and sync profiles first.
        </div>
      )}

      {/* Table */}
      {!noContext && !noProfiles && (
        <div className="card p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
                <th className="px-3 py-2.5 w-8">
                  <input
                    type="checkbox"
                    checked={allPageSelected}
                    onChange={toggleAll}
                    disabled={pendingFiltered.length === 0}
                    className="rounded border-gray-300 text-blue-600 disabled:opacity-30"
                    title="Select all pending on page"
                  />
                </th>
                <th className="px-3 py-2.5 text-left text-xs font-semibold text-gray-600 w-44">Search Term</th>
                <th className="px-3 py-2.5 text-left text-xs font-semibold text-gray-600 w-24">Type</th>
                <th className="px-3 py-2.5 text-left text-xs font-semibold text-gray-600">Reason</th>
                <th className="px-3 py-2.5 text-center text-xs font-semibold text-gray-600 w-20">Conf.</th>
                <th className="px-3 py-2.5 text-right text-xs font-semibold text-gray-600">Spend</th>
                <th className="px-3 py-2.5 text-right text-xs font-semibold text-gray-600">Sales</th>
                <th className="px-3 py-2.5 text-right text-xs font-semibold text-gray-600">Orders</th>
                <th className="px-3 py-2.5 text-right text-xs font-semibold text-gray-600">ACOS</th>
                <th className="px-3 py-2.5 text-left text-xs font-semibold text-gray-600 w-20">Status</th>
                <th className="px-3 py-2.5 text-left text-xs font-semibold text-gray-600 w-36">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr><td colSpan={11} className="px-4 py-12 text-center text-gray-400">Loading…</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={11} className="px-4 py-12 text-center text-gray-400">
                  {suggestions.length === 0
                    ? 'No suggestions yet. Sync search terms first, then generate suggestions.'
                    : 'No suggestions match your filters.'}
                </td></tr>
              ) : filtered.map(s => {
                const snap    = s.metrics_snapshot
                const isBusy  = actioning[s.id]
                const isSel   = selected.has(s.id)
                const isPending = s.status === 'pending'
                const conf    = s.confidence_score ?? 0
                return (
                  <tr
                    key={s.id}
                    className={`hover:bg-gray-50 cursor-pointer ${!isPending ? 'opacity-60' : ''} ${isSel ? 'bg-blue-50' : ''}`}
                    onClick={() => setDrawer(s)}
                  >
                    <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>
                      {isPending && (
                        <input
                          type="checkbox"
                          checked={isSel}
                          onChange={() => toggleRow(s.id)}
                          className="rounded border-gray-300 text-blue-600"
                        />
                      )}
                    </td>
                    <td className="px-3 py-2.5 font-medium text-gray-900 max-w-[176px] truncate" title={s.search_term}>
                      {s.search_term}
                      {s.source_type === 'rule' && (
                        <span className="ml-1.5 text-[10px] text-indigo-500" title={`Rule: ${s.source_rule_name}`}>⚙</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${TYPE_COLORS[s.suggestion_type] ?? 'bg-gray-100 text-gray-600'}`}>
                        {TYPE_LABELS[s.suggestion_type] ?? s.suggestion_type}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-gray-600 text-xs max-w-[220px] truncate" title={s.reason}>{s.reason}</td>
                    <td className="px-3 py-2.5 text-center">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${confidenceBadge(conf)}`}>
                        {conf}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-right text-gray-700">{fmtCurrency(s.total_spend)}</td>
                    <td className="px-3 py-2.5 text-right text-gray-700">{fmtCurrency(s.total_sales)}</td>
                    <td className="px-3 py-2.5 text-right text-gray-700">{s.total_orders ?? snap.orders}</td>
                    <td className="px-3 py-2.5 text-right text-gray-700">{fmtPct(snap.acos)}</td>
                    <td className="px-3 py-2.5">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[s.status] ?? ''}`}>
                        {s.status}
                      </span>
                    </td>
                    <td className="px-3 py-2.5" onClick={e => e.stopPropagation()}>
                      {isPending ? (
                        <div className="flex gap-1.5">
                          <button
                            onClick={() => handleApprove(s.id)}
                            disabled={isBusy}
                            className="text-xs px-2.5 py-1 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 transition-colors"
                          >
                            {isBusy ? '…' : 'Approve'}
                          </button>
                          <button
                            onClick={() => handleReject(s.id)}
                            disabled={isBusy}
                            className="text-xs px-2.5 py-1 bg-white border border-gray-300 text-gray-600 rounded hover:bg-gray-50 disabled:opacity-50 transition-colors"
                          >
                            {isBusy ? '…' : 'Reject'}
                          </button>
                        </div>
                      ) : (
                        <span className="text-xs text-gray-400 capitalize">{s.status}</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {filtered.length > 0 && (
            <div className="px-4 py-2 border-t border-gray-200 text-xs text-gray-400 flex items-center justify-between">
              <span>Showing {filtered.length} of {suggestions.length} suggestions</span>
              {selected.size > 0 && (
                <span className="text-blue-600">{selected.size} selected</span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Detail drawer */}
      {drawer && (
        <DetailDrawer s={drawer} onClose={() => setDrawer(null)} />
      )}
    </div>
  )
}

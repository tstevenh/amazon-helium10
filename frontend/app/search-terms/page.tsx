'use client'
import { useEffect, useState, useMemo, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useUrlState } from '@/lib/useUrlState'
import { useColumnWidths } from '@/components/ui/useColumnWidths'
import { useAuth } from '@/context/AuthContext'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { api, ApiError } from '@/lib/api'
import { SearchTermRow, Campaign, AdGroup } from '@/lib/types'

// ── helpers ──────────────────────────────────────────────────────────────────

function fmt(n: string | number | null | undefined, decimals = 2): string {
  if (n == null) return '—'
  const v = typeof n === 'string' ? parseFloat(n) : n
  if (isNaN(v)) return '—'
  return v.toFixed(decimals)
}

function fmtPct(n: string | null | undefined): string {
  if (n == null) return '—'
  const v = parseFloat(n)
  if (isNaN(v)) return '—'
  return (v * 100).toFixed(1) + '%'
}

function fmtCurrency(n: string | null | undefined): string {
  if (n == null) return '—'
  const v = parseFloat(n)
  if (isNaN(v)) return '—'
  return '$' + v.toFixed(2)
}

function today(): string {
  return new Date().toISOString().split('T')[0]
}

function daysAgo(d: number): string {
  const dt = new Date()
  dt.setDate(dt.getDate() - d)
  return dt.toISOString().split('T')[0]
}

type SortKey = keyof SearchTermRow | ''
type SortDir = 'asc' | 'desc'

const PAGE_SIZE = 25

const DATE_PRESETS = [
  { label: 'Last 7d',  from: () => daysAgo(7) },
  { label: 'Last 14d', from: () => daysAgo(14) },
  { label: 'Last 30d', from: () => daysAgo(30) },
  { label: 'Last 60d', from: () => daysAgo(60) },
]

// ── component ─────────────────────────────────────────────────────────────────

// Module scope: useUrlState memoises on this object's identity, so a literal
// built inside the component would be a new object every render.
//
// Empty date_from/date_to mean "the Last 30d preset", resolved at render time
// rather than stored, so a pasted link still means "the last 30 days"
// tomorrow instead of freezing today's dates.
const SEARCH_TERM_DEFAULTS = {
  date_from: '',
  date_to: '',
  campaign: '',
  ad_group: '',
  min_spend: '',
  min_sales: '',
  max_acos: '',
  search: '',
  preset: 'Last 30d',
  sort: 'cost',
  dir: 'desc',
}

export default function SearchTermsPage() {
  const router = useRouter()
  const { user, loading: authLoading } = useAuth()
  const {
    currentAccountId, currentProfileId, accountProfileIds,
    accountsLoading, profilesLoading,
  } = useAccountProfile()

  // Filters, date range and sort live in the URL rather than useState, so
  // Back from a drill-down restores them. See lib/useUrlState.ts.
  const [urlState, setUrlState] = useUrlState(SEARCH_TERM_DEFAULTS)
  const dateFrom = urlState.date_from || daysAgo(30)
  const dateTo = urlState.date_to || today()
  const campaignId = urlState.campaign
  const adGroupId = urlState.ad_group
  const minSpend = urlState.min_spend
  const minSales = urlState.min_sales
  const maxAcos = urlState.max_acos
  const search = urlState.search
  const activePreset = urlState.preset
  const setDateFrom = (v: string) => setUrlState({ date_from: v, preset: '' })
  const setDateTo = (v: string) => setUrlState({ date_to: v, preset: '' })
  // Changing campaign clears the ad group: an ad group from another campaign
  // would silently filter everything out and look like "no data".
  const setCampaignId = (v: string) => setUrlState({ campaign: v, ad_group: '' })
  const setAdGroupId = (v: string) => setUrlState({ ad_group: v })
  const setMinSpend = (v: string) => setUrlState({ min_spend: v })
  const setMinSales = (v: string) => setUrlState({ min_sales: v })
  const setMaxAcos = (v: string) => setUrlState({ max_acos: v })
  const setSearch = (v: string) => setUrlState({ search: v })

  // data
  const [rows,      setRows]      = useState<SearchTermRow[]>([])
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [adGroups, setAdGroups] = useState<AdGroup[]>([])
  // 12 columns, matching the header array below.
  const cols = useColumnWidths('search-terms', 12)
  const [loading,   setLoading]   = useState(false)
  const [syncing,   setSyncing]   = useState(false)
  const [error,     setError]     = useState<string | null>(null)
  const [syncMsg,   setSyncMsg]   = useState<string | null>(null)

  // sort + pagination
  const sortKey = urlState.sort as SortKey
  const sortDir: SortDir = urlState.dir === 'asc' ? 'asc' : 'desc'
  const [page,      setPage]      = useState(1)

  // auth guard
  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  // determine active profile IDs
  const profileIds: string[] = useMemo(() => {
    if (currentProfileId) return [currentProfileId]
    return Array.from(accountProfileIds)
  }, [currentProfileId, accountProfileIds])

  // load campaigns for filter dropdown
  useEffect(() => {
    if (!currentAccountId) return
    api.listCampaigns().then(data => {
      const filtered = currentProfileId
        ? data.filter(c => c.profile_id === currentProfileId)
        : data.filter(c => accountProfileIds.has(c.profile_id))
      setCampaigns(filtered)
    }).catch(() => {})
    api.listAdGroups().then(setAdGroups).catch(() => {})
  }, [currentAccountId, currentProfileId, accountProfileIds])

  // Only the ad groups that belong to the chosen campaign. Listing every ad
  // group in the marketplace would be hundreds of entries with no way to tell
  // which campaign each came from.
  const visibleAdGroups = useMemo(() => {
    const inScope = new Set(campaigns.map(c => c.id))
    return adGroups
      .filter(g => (campaignId ? g.campaign_id === campaignId : inScope.has(g.campaign_id)))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [adGroups, campaigns, campaignId])

  const load = useCallback(async () => {
    if (!profileIds.length || accountsLoading || profilesLoading) return
    setLoading(true)
    setError(null)
    try {
      // If multiple profiles, fetch each and merge
      const all: SearchTermRow[] = []
      for (const pid of profileIds) {
        const data = await api.listSearchTerms({
          profile_id: pid,
          date_from: dateFrom,
          date_to: dateTo,
          campaign_id: campaignId || undefined,
          ad_group_id: adGroupId || undefined,
          min_spend: minSpend ? parseFloat(minSpend) : undefined,
          min_sales: minSales ? parseFloat(minSales) : undefined,
          max_acos:  maxAcos  ? parseFloat(maxAcos) / 100 : undefined,
          q: search || undefined,
        })
        all.push(...data)
      }
      setRows(all)
      setPage(1)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load search terms')
    } finally {
      setLoading(false)
    }
  }, [profileIds, accountsLoading, profilesLoading, dateFrom, dateTo, campaignId, adGroupId, minSpend, minSales, maxAcos, search])

  useEffect(() => {
    if (user && !accountsLoading && profileIds.length) load()
  }, [user, accountsLoading, profileIds, load])

  function applyPreset(preset: typeof DATE_PRESETS[0]) {
    // One call, not three. Each setUrlState reads the state captured at this
    // render, so three sequential calls would each overwrite the previous
    // one's parameter and only the last would survive.
    setUrlState({ preset: preset.label, date_from: preset.from(), date_to: today() })
  }

  async function handleSync() {
    if (!currentAccountId) return
    setSyncing(true)
    setSyncMsg(null)
    setError(null)
    try {
      const res = await api.syncSearchTerms(currentAccountId)
      setSyncMsg(`Synced ${res.terms_synced} terms · ${res.suggestions_generated} suggestions generated`)
      await load()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Sync failed')
    } finally {
      setSyncing(false)
    }
  }

  // sort
  const sorted = useMemo(() => {
    if (!sortKey) return rows
    return [...rows].sort((a, b) => {
      const av = parseFloat(String((a as any)[sortKey] ?? 0)) || 0
      const bv = parseFloat(String((b as any)[sortKey] ?? 0)) || 0
      return sortDir === 'asc' ? av - bv : bv - av
    })
  }, [rows, sortKey, sortDir])

  const totalPages = Math.ceil(sorted.length / PAGE_SIZE)
  const pageRows   = sorted.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  function handleSort(key: SortKey) {
    if (sortKey === key) setUrlState({ dir: sortDir === 'asc' ? 'desc' : 'asc' })
    else setUrlState({ sort: String(key), dir: 'desc' })
  }

  function SortIndicator({ k }: { k: SortKey }) {
    if (sortKey !== k) return <span className="text-gray-300 ml-1">↕</span>
    return <span className="text-blue-500 ml-1">{sortDir === 'asc' ? '↑' : '↓'}</span>
  }

  const noContext = !accountsLoading && !currentAccountId
  const noProfiles = !profilesLoading && currentAccountId && profileIds.length === 0

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Search Terms</h1>
          {!loading && rows.length > 0 && (
            <p className="text-sm text-gray-500 mt-0.5">{rows.length} terms found</p>
          )}
        </div>
        <button
          onClick={handleSync}
          disabled={syncing || !currentAccountId}
          className="btn-primary"
        >
          {syncing ? 'Syncing…' : 'Sync Search Terms'}
        </button>
      </div>

      {syncMsg && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2 text-sm text-green-700">
          {syncMsg}
        </div>
      )}

      {/* Filters */}
      <div className="card space-y-3">
        {/* Date presets */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium text-gray-500">Date range:</span>
          {DATE_PRESETS.map(p => (
            <button
              key={p.label}
              onClick={() => applyPreset(p)}
              className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                activePreset === p.label
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-gray-600 border-gray-300 hover:border-blue-400'
              }`}
            >
              {p.label}
            </button>
          ))}
          <div className="flex items-center gap-1 ml-2">
            <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
              className="input text-xs py-1 px-2 w-36" />
            <span className="text-gray-400 text-xs">to</span>
            <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
              className="input text-xs py-1 px-2 w-36" />
          </div>
        </div>

        {/* Row 2: campaign, spend, sales, ACOS, search */}
        <div className="flex flex-wrap gap-2 items-end">
          <div>
            <label className="label">Campaign</label>
            <select value={campaignId} onChange={e => setCampaignId(e.target.value)} className="input text-sm">
              <option value="">All Campaigns</option>
              {campaigns.map(c => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Ad Group</label>
            <select value={adGroupId} onChange={e => setAdGroupId(e.target.value)}
                    className="input text-sm max-w-[180px]">
              <option value="">All Ad Groups</option>
              {visibleAdGroups.map(g => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Min Spend ($)</label>
            <input type="number" min="0" step="0.01" value={minSpend}
              onChange={e => setMinSpend(e.target.value)}
              placeholder="0.00" className="input text-sm w-28" />
          </div>
          <div>
            <label className="label">Min Sales ($)</label>
            <input type="number" min="0" step="0.01" value={minSales}
              onChange={e => setMinSales(e.target.value)}
              placeholder="0.00" className="input text-sm w-28" />
          </div>
          <div>
            <label className="label">Max ACOS (%)</label>
            <input type="number" min="0" step="1" value={maxAcos}
              onChange={e => setMaxAcos(e.target.value)}
              placeholder="e.g. 30" className="input text-sm w-28" />
          </div>
          <div className="flex-1 min-w-[180px]">
            <label className="label">Search</label>
            <input type="search" value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Filter by search term…" className="input text-sm w-full" />
          </div>
          <button onClick={load} className="btn-primary text-sm">Apply</button>
          <button onClick={() => {
            setMinSpend(''); setMinSales(''); setMaxAcos(''); setSearch(''); setCampaignId('')
          }} className="btn-secondary text-sm">Clear</button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Empty / no-context states */}
      {noContext && (
        <div className="card text-center py-12 text-gray-500">Select an account to view search terms.</div>
      )}
      {noProfiles && (
        <div className="card text-center py-12 text-gray-500">
          No profiles synced for this account. Go to Settings → Accounts and sync profiles, then sync search terms.
        </div>
      )}

      {/* Table */}
      {!noContext && !noProfiles && (
        <div className="card p-0 overflow-x-auto">
          <table className="w-full text-sm" style={cols.tableStyle}>
            {cols.colGroup}
            <thead ref={cols.theadRef}>
              <tr className="border-b border-gray-200 bg-gray-50">
                {[
                  { label: 'Search Term',  key: 'search_term' as SortKey, cls: 'text-left w-56' },
                  { label: 'Campaign',     key: '' as SortKey,            cls: 'text-left w-40' },
                  { label: 'Ad Group',     key: '' as SortKey,            cls: 'text-left w-40' },
                  { label: 'Impressions',  key: 'impressions' as SortKey, cls: 'text-right' },
                  { label: 'Clicks',       key: 'clicks' as SortKey,      cls: 'text-right' },
                  { label: 'Spend',        key: 'cost' as SortKey,        cls: 'text-right' },
                  { label: 'Sales',        key: 'sales' as SortKey,       cls: 'text-right' },
                  { label: 'Orders',       key: 'orders' as SortKey,      cls: 'text-right' },
                  { label: 'ACOS',         key: 'acos' as SortKey,        cls: 'text-right' },
                  { label: 'ROAS',         key: 'roas' as SortKey,        cls: 'text-right' },
                  { label: 'CTR',          key: 'ctr' as SortKey,         cls: 'text-right' },
                  { label: 'CVR',          key: 'conversion_rate' as SortKey, cls: 'text-right' },
                ].map((col, i, arr) => (
                  <th key={col.label}
                    className={`relative px-3 py-2.5 text-xs font-semibold text-gray-600 whitespace-nowrap ${col.cls} ${col.key ? 'cursor-pointer hover:bg-gray-100' : ''}`}
                    onClick={() => col.key && handleSort(col.key)}
                  >
                    {col.label}{col.key && <SortIndicator k={col.key} />}
                    {i < arr.length - 1 && cols.handle(i)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr><td colSpan={12} className="px-4 py-12 text-center text-gray-400">Loading…</td></tr>
              ) : pageRows.length === 0 ? (
                <tr><td colSpan={12} className="px-4 py-12 text-center text-gray-400">
                  No search terms found. Run Sync Search Terms to import data.
                </td></tr>
              ) : pageRows.map((row, i) => {
                const acosVal = row.acos ? parseFloat(row.acos) : null
                const acosColor = acosVal == null ? '' :
                  acosVal < 0.25 ? 'text-green-600' :
                  acosVal < 0.50 ? 'text-yellow-600' : 'text-red-600'
                return (
                  <tr key={`${row.search_term}-${i}`} className="hover:bg-gray-50">
                    <td className="px-3 py-2.5 font-medium text-gray-900 max-w-[224px] truncate" title={row.search_term}>
                      {row.search_term}
                    </td>
                    <td className="px-3 py-2.5 text-gray-500 max-w-[160px] truncate" title={row.campaign_name ?? ''}>
                      {row.campaign_name ?? '—'}
                    </td>
                    {/* Rows were already grouped per ad group, but only the
                        campaign was shown — so the same search term in two ad
                        groups looked like a duplicated row. */}
                    <td className="px-3 py-2.5 text-gray-500 max-w-[160px] truncate" title={row.ad_group_name ?? ''}>
                      {row.ad_group_name ?? '—'}
                    </td>
                    <td className="px-3 py-2.5 text-right text-gray-700">{row.impressions.toLocaleString()}</td>
                    <td className="px-3 py-2.5 text-right text-gray-700">{row.clicks.toLocaleString()}</td>
                    <td className="px-3 py-2.5 text-right text-gray-700">{fmtCurrency(row.cost)}</td>
                    <td className="px-3 py-2.5 text-right text-gray-700">{fmtCurrency(row.sales)}</td>
                    <td className="px-3 py-2.5 text-right text-gray-700">{row.orders}</td>
                    <td className={`px-3 py-2.5 text-right font-medium ${acosColor}`}>{fmtPct(row.acos)}</td>
                    <td className="px-3 py-2.5 text-right text-gray-700">{row.roas ? fmt(row.roas) + 'x' : '—'}</td>
                    <td className="px-3 py-2.5 text-right text-gray-700">{fmtPct(row.ctr)}</td>
                    <td className="px-3 py-2.5 text-right text-gray-700">{fmtPct(row.conversion_rate)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="px-4 py-3 border-t border-gray-200 flex items-center justify-between text-sm text-gray-600">
              <span>{sorted.length} terms · page {page} of {totalPages}</span>
              <div className="flex gap-2">
                <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
                  className="btn-secondary text-xs px-3 py-1 disabled:opacity-40">← Prev</button>
                <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages}
                  className="btn-secondary text-xs px-3 py-1 disabled:opacity-40">Next →</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

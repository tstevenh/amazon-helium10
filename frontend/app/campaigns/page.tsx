'use client'
import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { useUrlState } from '@/lib/useUrlState'
import { useAuth } from '@/context/AuthContext'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { api, ApiError } from '@/lib/api'
import type { CampaignWithMetrics, Profile } from '@/lib/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, Column, SortDir } from '@/components/ui/DataTable'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { SearchBox } from '@/components/ui/SearchBox'
import { Card } from '@/components/ui/Card'
import { StatBar } from '@/components/ui/StatBar'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { Input } from '@/components/ui/Field'
import { FilterBar, FilterConfig } from '@/components/ui/FilterBar'
import { LoadingState } from '@/components/ui/LoadingState'
import { ErrorState } from '@/components/ui/ErrorState'
import { EmptyState } from '@/components/ui/EmptyState'
import { emptyDataMessage } from '@/lib/emptyState'

// ── Date range helpers ─────────────────────────────────────────────────────

type Preset = '7d' | '14d' | '30d' | '90d'

function isoDate(d: Date) { return d.toISOString().slice(0, 10) }

function datesForPreset(p: Preset): { date_from: string; date_to: string } {
  const to = new Date(); to.setDate(to.getDate() - 1)
  const from = new Date(to)
  const days = p === '7d' ? 6 : p === '14d' ? 13 : p === '30d' ? 29 : 89
  from.setDate(from.getDate() - days)
  return { date_from: isoDate(from), date_to: isoDate(to) }
}

// ── Metric formatters ──────────────────────────────────────────────────────

const fmt = {
  currency: (v: number | null | undefined) =>
    v == null ? '—' : `$${Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
  int:  (v: number | null | undefined) => v == null ? '—' : Number(v).toLocaleString('en-US'),
  pct:  (v: number | null | undefined) => v == null ? '—' : `${(Number(v) * 100).toFixed(2)}%`,
  acos: (v: number | null | undefined) => v == null ? '—' : `${Number(v).toFixed(1)}%`,
  roas: (v: number | null | undefined) => v == null ? '—' : Number(v).toFixed(2),
}

// ── Main page ─────────────────────────────────────────────────────────────

// Declared at module scope on purpose. useUrlState memoises on this object's
// identity, so a literal built inside the component would be a new object every
// render and defeat the memo. `sort` holds a column HEADER rather than an index
// so reordering columns cannot silently change what a saved link sorts by, and
// empty date_from/date_to mean "the 30-day default", resolved at render time.
const CAMPAIGN_FILTER_DEFAULTS = {
  search: '',
  status: 'all',
  ad_product: 'all',
  date_from: '',
  date_to: '',
  sort: 'Spend',
  dir: 'desc',
}

export default function CampaignsPage() {
  const { user, loading: authLoading } = useAuth()
  const {
    currentAccountId, currentProfileId, currentAccount,
    profiles, accountProfileIds, accountsLoading, profilesLoading, profileCounts, setCurrentProfile } = useAccountProfile()
  const router = useRouter()

  const [campaigns, setCampaigns] = useState<CampaignWithMetrics[]>([])
  // Filters, date range and sort live in the URL, not in useState. Pressing
  // Back from a campaign used to remount this screen with its defaults, so
  // "7 days sorted by clicks" silently reverted to "30 days sorted by spend".
  // Defaults are declared once, outside render, so the object identity is
  // stable and useUrlState's memo does not invalidate on every render.
  const [urlState, setUrlState] = useUrlState(CAMPAIGN_FILTER_DEFAULTS)
  const { search, status: statusFilter, ad_product: adProductFilter } = urlState
  const setSearch = (v: string) => setUrlState({ search: v })
  const setStatusFilter = (v: string) => setUrlState({ status: v })
  const setAdProductFilter = (v: string) => setUrlState({ ad_product: v })
  const [dataLoading, setDataLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Shared date range, also from the URL. An empty value means "the 30-day
  // default", resolved here rather than stored, so the URL stays clean and a
  // pasted link keeps meaning "last 30 days" tomorrow instead of freezing
  // today's dates.
  const dateFrom = urlState.date_from || datesForPreset('30d').date_from
  const dateTo = urlState.date_to || datesForPreset('30d').date_to
  const setDateRange = (from: string, to: string) =>
    setUrlState({ date_from: from, date_to: to })

  const activePreset = useMemo((): Preset | null => {
    for (const p of ['7d', '14d', '30d', '90d'] as Preset[]) {
      const d = datesForPreset(p)
      if (d.date_from === dateFrom && d.date_to === dateTo) return p
    }
    return null
  }, [dateFrom, dateTo])

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async (from: string, to: string) => {
    if (!currentAccountId) return
    setDataLoading(true)
    setError(null)
    setCampaigns([])
    try {
      const params: Record<string, string> = { date_from: from, date_to: to }
      if (currentProfileId) {
        params.profile_id = currentProfileId
      } else {
        params.account_id = currentAccountId
      }
      const data = await api.getCampaignsWithMetrics(params)
      setCampaigns(data)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load campaigns')
    } finally {
      setDataLoading(false)
    }
  }, [currentAccountId, currentProfileId])

  useEffect(() => {
    if (user && !accountsLoading && currentAccountId) load(dateFrom, dateTo)
  }, [user, accountsLoading, currentAccountId, load, dateFrom, dateTo])

  const profileMap = useMemo<Record<string, Profile>>(() => {
    const map: Record<string, Profile> = {}
    profiles.forEach(p => { map[p.id] = p })
    return map
  }, [profiles])

  const contextFiltered = useMemo(() => {
    if (!currentAccountId || profilesLoading) return []
    if (currentProfileId) return campaigns.filter(c => c.profile_id === currentProfileId)
    if (accountProfileIds.size === 0) return []
    return campaigns.filter(c => accountProfileIds.has(c.profile_id))
  }, [campaigns, currentAccountId, currentProfileId, accountProfileIds, profilesLoading])

  const filtered = useMemo(() => contextFiltered.filter(c => {
    const matchSearch = c.name.toLowerCase().includes(search.toLowerCase())
    const matchStatus = statusFilter === 'all' || c.status === statusFilter
    const matchType = adProductFilter === 'all' || c.ad_product === adProductFilter
    return matchSearch && matchStatus && matchType
  }), [contextFiltered, search, statusFilter, adProductFilter])

  // Totals for the rows currently shown. Derived from `filtered` rather than
  // fetched separately, so the strip can never disagree with the table.
  const kpis = useMemo(() => {
    const sum = (pick: (r: typeof filtered[number]) => number | null | undefined) =>
      filtered.reduce((acc, r) => acc + (Number(pick(r)) || 0), 0)
    const spend  = sum(r => r.spend)
    const sales  = sum(r => r.sales)
    const clicks = sum(r => r.clicks)
    const orders = sum(r => r.orders)
    return {
      spend, sales, clicks, orders,
      acos: sales > 0 ? (spend / sales) * 100 : null,
      roas: spend > 0 ? sales / spend : null,
    }
  }, [filtered])

  if (authLoading || accountsLoading) return <LoadingState message="Loading…" />
  if (!user) return null
  if (error) return <ErrorState message={error} onRetry={() => load(dateFrom, dateTo)} />

  if (!currentAccountId) {
    return (
      <EmptyState
        title="No account selected"
        description="Use the Account selector in the header to choose a seller account."
      />
    )
  }

  const filters: FilterConfig[] = [
    {
      key: 'status', label: 'Status', value: statusFilter, onChange: setStatusFilter,
      options: [
        { value: 'all', label: 'All Statuses' },
        { value: 'enabled', label: 'Enabled' },
        { value: 'paused', label: 'Paused' },
        { value: 'archived', label: 'Archived' },
      ],
    },
    {
      key: 'ad_product', label: 'Type', value: adProductFilter, onChange: setAdProductFilter,
      options: [
        { value: 'all', label: 'All Types' },
        { value: 'SP', label: 'Sponsored Products' },
        { value: 'SB', label: 'Sponsored Brands' },
        { value: 'SD', label: 'Sponsored Display' },
      ],
    },
  ]


  const columns: Column<CampaignWithMetrics>[] = [
    {
      header: 'Campaign',
      cell: row => <span className="font-medium text-ink">{row.name}</span>,
      sortValue: row => row.name,
    },
    {
      header: 'Type',
      cell: row => (
        <span className="text-xs font-mono bg-surface-sunken rounded px-2 py-0.5">{row.ad_product}</span>
      ),
      sortValue: row => row.ad_product,
    },
    {
      header: 'Status',
      cell: row => <StatusBadge status={row.status} />,
      sortValue: row => row.status,
    },
    {
      header: 'Spend',
      cell: row => <span className={`text-sm ${row.spend != null ? 'text-ink font-medium' : 'text-ink-subtle'}`}>{fmt.currency(row.spend)}</span>,
      sortValue: row => row.spend ?? -1,
    },
    {
      header: 'Sales',
      cell: row => <span className={`text-sm ${row.sales != null ? 'text-ink' : 'text-ink-subtle'}`}>{fmt.currency(row.sales)}</span>,
      sortValue: row => row.sales ?? -1,
    },
    {
      header: 'ACOS',
      cell: row => {
        const v = row.acos != null ? Number(row.acos) : null
        const color = v == null ? 'text-ink-subtle' : v > 40 ? 'text-danger' : v > 25 ? 'text-warn' : 'text-ok'
        return <span className={`text-sm font-medium ${color}`}>{fmt.acos(row.acos)}</span>
      },
      sortValue: row => row.acos ?? 9999,
    },
    {
      header: 'ROAS',
      cell: row => <span className={`text-sm ${row.roas != null ? 'text-ink' : 'text-ink-subtle'}`}>{fmt.roas(row.roas)}</span>,
      sortValue: row => row.roas ?? -1,
    },
    {
      header: 'Clicks',
      cell: row => <span className="text-sm text-ink">{fmt.int(row.clicks)}</span>,
      sortValue: row => row.clicks ?? -1,
    },
    {
      header: 'Impr.',
      cell: row => <span className="text-sm text-ink-muted">{fmt.int(row.impressions)}</span>,
      sortValue: row => row.impressions ?? -1,
    },
    {
      header: 'CPC',
      cell: row => <span className="text-sm text-ink-muted">{fmt.currency(row.cpc)}</span>,
      sortValue: row => row.cpc ?? -1,
    },
    {
      header: 'CTR',
      cell: row => <span className="text-sm text-ink-muted">{fmt.pct(row.ctr)}</span>,
      sortValue: row => row.ctr ?? -1,
    },
    {
      header: 'Budget',
      cell: row => <span className="text-sm text-ink-muted">{fmt.currency(row.daily_budget)}</span>,
      sortValue: row => row.daily_budget ?? 0,
    },
  ]

  // Sort is stored as a column header in the URL; map it back to an index.
  // An unknown header (a saved link from an older column set) falls back to
  // the default rather than rendering an unsorted table.
  // Deliberately NOT useMemo. This sits after the early returns above
  // (authLoading / !user / error), so a hook here runs on some renders and not
  // others — React counts hooks by position and crashed the whole screen with
  // "Rendered more hooks than during the previous render". A findIndex over a
  // dozen columns costs nothing; a conditional hook costs the page.
  const sortColFound = columns.findIndex(c => c.header === urlState.sort)
  const sortCol =
    sortColFound >= 0 ? sortColFound : columns.findIndex(c => c.header === 'Spend')
  const sortDir: SortDir = urlState.dir === 'asc' ? 'asc' : 'desc'

  const isLoading = dataLoading || profilesLoading
  const presets: Preset[] = ['7d', '14d', '30d', '90d']
  const presetLabels: Record<Preset, string> = { '7d': '7D', '14d': '14D', '30d': '30D', '90d': '90D' }

  return (
    <div>
      <PageHeader
        title="Campaigns"
        subtitle={
          isLoading
            ? 'Loading…'
            : `${filtered.length} of ${contextFiltered.length} campaign${contextFiltered.length !== 1 ? 's' : ''}`
        }
      />

      {/* Date range. A preset and an explicit range are the same setting, so they
          sit together with the presets first — nine times out of ten one click
          is the whole interaction. */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <SegmentedControl
          ariaLabel="Date range preset"
          value={activePreset}
          onChange={p => { const d = datesForPreset(p); setDateRange(d.date_from, d.date_to) }}
          options={presets.map(p => ({ value: p, label: presetLabels[p] }))}
        />
        <div className="flex items-center gap-1.5">
          <Input
            type="date"
            value={dateFrom}
            max={dateTo}
            onChange={e => setDateRange(e.target.value, dateTo)}
            aria-label="From date"
            className="w-[8.5rem] text-xs"
          />
          <span className="text-xs text-ink-faint" aria-hidden>–</span>
          <Input
            type="date"
            value={dateTo}
            min={dateFrom}
            max={isoDate(new Date())}
            onChange={e => setDateRange(dateFrom, e.target.value)}
            aria-label="To date"
            className="w-[8.5rem] text-xs"
          />
        </div>
      </div>

      {/* Totals for the rows currently shown, so they always agree with the
          table below rather than describing some wider set. */}
      <StatBar
        stats={[
          { label: 'Spend',  value: fmt.currency(kpis.spend) },
          { label: 'Sales',  value: fmt.currency(kpis.sales) },
          { label: 'ACOS',   value: kpis.acos == null ? '—' : `${kpis.acos.toFixed(1)}%` },
          { label: 'ROAS',   value: kpis.roas == null ? '—' : `${kpis.roas.toFixed(2)}×` },
          { label: 'Clicks', value: kpis.clicks.toLocaleString() },
          { label: 'Orders', value: kpis.orders.toLocaleString(),
            // Orders is the only figure here that is a count of outcomes rather
            // than a rate or a sum, so it carries what it is a count of.
            hint: 'in range' },
        ]}
      />

      {/* Card, not `card overflow-x-auto`: DataTable owns its own horizontal
          scroller, and nesting a second one produced two scrollbars where the
          outer clipped the inner. The filter row is padded; the table runs
          edge to edge, because a table inset from its own border reads as a
          picture of a table. */}
      <Card>
        <div className="flex flex-col gap-3 border-b border-hairline p-3 sm:flex-row">
          <SearchBox
            value={search}
            onChange={setSearch}
            placeholder="Search campaigns…"
            className="flex-1"
          />
          <FilterBar filters={filters} />
        </div>
        <DataTable
          // Open on highest spend: a PPC operator wants the campaigns
          // costing money first, not paused ones with no data. Computed
          // from the header so reordering columns cannot break it.
          sortCol={sortCol}
          sortDir={sortDir}
          onSortChange={(col, dir) =>
            setUrlState({ sort: col === null ? '' : columns[col].header, dir })
          }
          columns={columns}
          rows={filtered}
          rowKey={r => r.id}
          onRowClick={r => router.push(`/campaigns/${r.id}`)}
          rowHref={r => `/campaigns/${r.id}`}
          resizeKey="campaigns"
          loading={isLoading}
          emptyTitle="No campaigns found"
          emptyDescription={
            accountProfileIds.size === 0
              ? `No profiles synced for ${currentAccount?.name ?? 'this account'}.`
              : emptyDataMessage({ entity: 'campaigns', profileCounts,
                                   currentProfileId, accountName: currentAccount?.name }).message
          }
        />
      </Card>
    </div>
  )
}

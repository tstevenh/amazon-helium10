'use client'
import { useEffect, useState, useCallback, useMemo } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { api, ApiError } from '@/lib/api'
import type { AdGroup, TargetWithMetrics, PerfMetrics } from '@/lib/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, Column } from '@/components/ui/DataTable'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { SearchBox } from '@/components/ui/SearchBox'
import { FilterBar, FilterConfig } from '@/components/ui/FilterBar'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="py-3 flex">
      <dt className="w-40 text-sm font-medium text-ink-muted shrink-0">{label}</dt>
      <dd className="text-sm text-ink">{value}</dd>
    </div>
  )
}

// ── Metric helpers ────────────────────────────────────────────────────────

const fmt = {
  currency: (v: number | null | undefined) =>
    v == null ? '—' : `$${Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
  int:  (v: number | null | undefined) => v == null ? '—' : Number(v).toLocaleString('en-US'),
  pct:  (v: number | null | undefined) => v == null ? '—' : `${(Number(v) * 100).toFixed(2)}%`,
  acos: (v: number | null | undefined) => v == null ? '—' : `${Number(v).toFixed(1)}%`,
  roas: (v: number | null | undefined) => v == null ? '—' : Number(v).toFixed(2),
}

// ── Date range helpers ────────────────────────────────────────────────────

type Preset = '7d' | '14d' | '30d' | '90d'

function isoDate(d: Date) { return d.toISOString().slice(0, 10) }

function datesForPreset(p: Preset) {
  const to = new Date(); to.setDate(to.getDate() - 1)
  const from = new Date(to)
  const days = p === '7d' ? 6 : p === '14d' ? 13 : p === '30d' ? 29 : 89
  from.setDate(from.getDate() - days)
  return { date_from: isoDate(from), date_to: isoDate(to) }
}

function defaultDateRange() { return datesForPreset('30d') }

// ── DateRangePicker component ─────────────────────────────────────────────

function DateRangePicker({
  dateFrom, dateTo, onChange,
}: {
  dateFrom: string
  dateTo: string
  onChange: (from: string, to: string) => void
}) {
  const presets: Preset[] = ['7d', '14d', '30d', '90d']
  const presetLabels: Record<Preset, string> = { '7d': '7D', '14d': '14D', '30d': '30D', '90d': '90D' }

  const activePreset = useMemo((): Preset | null => {
    for (const p of presets) {
      const d = datesForPreset(p)
      if (d.date_from === dateFrom && d.date_to === dateTo) return p
    }
    return null
  }, [dateFrom, dateTo])

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <div className="flex rounded border border-hairline overflow-hidden text-xs">
        {presets.map(p => (
          <button
            key={p}
            onClick={() => { const d = datesForPreset(p); onChange(d.date_from, d.date_to) }}
            className={`px-2.5 py-1.5 ${activePreset === p ? 'bg-accent text-white' : 'bg-surface text-ink-muted hover:bg-surface-sunken'}`}
          >
            {presetLabels[p]}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-1 text-xs text-ink-muted">
        <input
          type="date"
          value={dateFrom}
          max={dateTo}
          onChange={e => onChange(e.target.value, dateTo)}
          className="border border-hairline rounded px-2 py-1 text-xs text-ink"
        />
        <span>–</span>
        <input
          type="date"
          value={dateTo}
          min={dateFrom}
          max={isoDate(new Date())}
          onChange={e => onChange(dateFrom, e.target.value)}
          className="border border-hairline rounded px-2 py-1 text-xs text-ink"
        />
      </div>
    </div>
  )
}

// ── Performance summary card ───────────────────────────────────────────────

function MetricTile({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="bg-surface-sunken rounded-lg p-3 text-center">
      <p className="text-[11px] text-ink-muted uppercase tracking-wide mb-0.5">{label}</p>
      <p className={`text-sm font-semibold ${highlight ? 'text-accent' : 'text-ink'}`}>{value}</p>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function AdGroupDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { user, loading: authLoading } = useAuth()
  const router = useRouter()
  const [adGroup, setAdGroup] = useState<AdGroup | null>(null)
  const [targets, setTargets] = useState<TargetWithMetrics[]>([])
  const [perfSummary, setPerfSummary] = useState<PerfMetrics | null>(null)
  const [perfNoData, setPerfNoData] = useState(false)
  const [search, setSearch] = useState('')
  const [kindFilter, setKindFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [dataLoading, setDataLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [dateFrom, setDateFrom] = useState(defaultDateRange().date_from)
  const [dateTo, setDateTo] = useState(defaultDateRange().date_to)

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async (from: string, to: string) => {
    setDataLoading(true)
    setError(null)
    try {
      const [ag, tgts, perf] = await Promise.all([
        api.getAdGroup(id),
        api.getAdGroupTargetsWithMetrics(id, { date_from: from, date_to: to }),
        api.getAdGroupPerfSummary(id, { date_from: from, date_to: to }),
      ])
      setAdGroup(ag)
      setTargets(tgts)
      const hasData = perf && perf.impressions != null
      setPerfSummary(hasData ? perf : null)
      setPerfNoData(!hasData)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load ad group')
    } finally {
      setDataLoading(false)
    }
  }, [id])

  useEffect(() => {
    if (user) load(dateFrom, dateTo)
  }, [user, load, dateFrom, dateTo])

  const handleDateChange = useCallback((from: string, to: string) => {
    setDateFrom(from)
    setDateTo(to)
  }, [])

  const filtered = useMemo(() => targets.filter(t => {
    const text = t.expression_text?.toLowerCase() ?? ''
    const matchSearch = !search || text.includes(search.toLowerCase())
    const matchKind = kindFilter === 'all' || t.target_kind === kindFilter
    const matchStatus = statusFilter === 'all' || t.status === statusFilter
    return matchSearch && matchKind && matchStatus
  }), [targets, search, kindFilter, statusFilter])

  if (authLoading) return <LoadingState message="Checking authentication…" />
  if (!user) return null
  if (error) return <ErrorState message={error} onRetry={() => load(dateFrom, dateTo)} />
  if (dataLoading) return <LoadingState />
  if (!adGroup) return null

  const filters: FilterConfig[] = [
    {
      key: 'kind', label: 'Kind', value: kindFilter, onChange: setKindFilter,
      options: [
        { value: 'all', label: 'All Kinds' },
        { value: 'keyword', label: 'Keyword' },
        { value: 'product', label: 'Product' },
        { value: 'audience', label: 'Audience' },
      ],
    },
    {
      key: 'status', label: 'Status', value: statusFilter, onChange: setStatusFilter,
      options: [
        { value: 'all', label: 'All Statuses' },
        { value: 'enabled', label: 'Enabled' },
        { value: 'paused', label: 'Paused' },
        { value: 'archived', label: 'Archived' },
      ],
    },
  ]

  const columns: Column<TargetWithMetrics>[] = [
    {
      header: 'Target',
      cell: row => <span className="font-medium text-ink text-xs">{row.expression_text || '—'}</span>,
      sortValue: row => row.expression_text ?? '',
    },
    {
      header: 'Kind',
      cell: row => (
        <span className="text-xs font-mono bg-surface-sunken rounded px-2 py-0.5 capitalize">
          {row.target_kind}
        </span>
      ),
      sortValue: row => row.target_kind,
    },
    {
      header: 'Match',
      cell: row => <span className="text-ink-muted text-xs capitalize">{row.match_type ?? '—'}</span>,
    },
    {
      header: 'Status',
      cell: row => <StatusBadge status={row.status} />,
      sortValue: row => row.status,
    },
    {
      header: 'Spend',
      cell: row => <span className="text-ink text-xs">{fmt.currency(row.spend)}</span>,
      sortValue: row => row.spend ?? -1,
    },
    {
      header: 'Sales',
      cell: row => <span className="text-ink text-xs">{fmt.currency(row.sales)}</span>,
      sortValue: row => row.sales ?? -1,
    },
    {
      header: 'ACOS',
      cell: row => {
        const acos = row.acos
        const color = acos == null ? 'text-ink-subtle'
          : acos > 40 ? 'text-danger font-medium'
          : acos > 25 ? 'text-warn font-medium'
          : 'text-ok font-medium'
        return <span className={`text-xs ${color}`}>{fmt.acos(acos)}</span>
      },
      sortValue: row => row.acos ?? 9999,
    },
    {
      header: 'ROAS',
      cell: row => <span className="text-ink text-xs">{fmt.roas(row.roas)}</span>,
      sortValue: row => row.roas ?? -1,
    },
    {
      header: 'Clicks',
      cell: row => <span className="text-ink text-xs">{fmt.int(row.clicks)}</span>,
      sortValue: row => row.clicks ?? -1,
    },
    {
      header: 'Bid',
      cell: row => (
        <span className="text-ink text-xs">
          {row.bid != null ? `$${Number(row.bid).toFixed(2)}` : '—'}
        </span>
      ),
      sortValue: row => row.bid ?? 0,
    },
  ]

  return (
    <div>
      <button
        onClick={() => router.back()}
        className="text-sm text-accent hover:underline mb-4 inline-block"
      >
        ← Back
      </button>
      <PageHeader
        title={adGroup.name}
        subtitle={`Ad Group · ${adGroup.status}`}
        actions={<StatusBadge status={adGroup.status} />}
      />

      {/* Performance card */}
      <div className="card mb-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-3">
          <h2 className="text-sm font-semibold text-ink">Performance</h2>
          <DateRangePicker dateFrom={dateFrom} dateTo={dateTo} onChange={handleDateChange} />
        </div>
        {dataLoading ? (
          <p className="text-xs text-ink-subtle py-4 text-center">Loading metrics…</p>
        ) : perfNoData ? (
          <p className="text-xs text-ink-subtle py-4 text-center">
            No performance data for this range. Run Sync All from Campaign Manager first.
          </p>
        ) : perfSummary ? (
          <div className="grid grid-cols-4 sm:grid-cols-8 gap-2">
            <MetricTile label="Spend"  value={fmt.currency(perfSummary.spend)}  highlight />
            <MetricTile label="Sales"  value={fmt.currency(perfSummary.sales)} />
            <MetricTile label="ACOS"   value={fmt.acos(perfSummary.acos)} />
            <MetricTile label="ROAS"   value={fmt.roas(perfSummary.roas)} />
            <MetricTile label="Clicks" value={fmt.int(perfSummary.clicks)} />
            <MetricTile label="Impr."  value={fmt.int(perfSummary.impressions)} />
            <MetricTile label="CTR"    value={fmt.pct(perfSummary.ctr)} />
            <MetricTile label="CPC"    value={fmt.currency(perfSummary.cpc)} />
          </div>
        ) : null}
      </div>

      <div className="card mb-6">
        <h2 className="text-sm font-semibold text-ink mb-2">Ad Group Details</h2>
        <dl className="divide-y divide-hairline">
          <DetailRow label="Status" value={<StatusBadge status={adGroup.status} />} />
          <DetailRow
            label="Default Bid"
            value={adGroup.default_bid != null ? `$${Number(adGroup.default_bid).toFixed(2)}` : '—'}
          />
        </dl>
      </div>

      <div className="card">
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 mb-4">
          <h2 className="text-sm font-semibold text-ink shrink-0">
            Targets ({filtered.length}{search || kindFilter !== 'all' || statusFilter !== 'all' ? ` of ${targets.length}` : ''})
          </h2>
          <div className="flex gap-2 flex-1 w-full sm:w-auto">
            <SearchBox
              value={search}
              onChange={setSearch}
              placeholder="Search targets…"
              className="flex-1"
            />
            <FilterBar filters={filters} />
          </div>
        </div>
        <DataTable
          columns={columns}
          rows={filtered}
          rowKey={r => r.id}
          emptyTitle="No targets"
          emptyDescription={search ? 'No targets match your search.' : 'No targets found for this ad group.'}
        />
      </div>
    </div>
  )
}

'use client'
import { useEffect, useState, useCallback, useMemo } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { api, ApiError } from '@/lib/api'
import type { Campaign, AdGroupWithMetrics, PerfMetrics } from '@/lib/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, Column } from '@/components/ui/DataTable'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { SearchBox } from '@/components/ui/SearchBox'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="py-3 flex">
      <dt className="w-40 text-sm font-medium text-gray-500 shrink-0">{label}</dt>
      <dd className="text-sm text-gray-900">{value}</dd>
    </div>
  )
}

// ── Metric formatters ─────────────────────────────────────────────────────

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

// ── DateRangePicker ───────────────────────────────────────────────────────

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
      <div className="flex rounded border border-gray-200 overflow-hidden text-xs">
        {presets.map(p => (
          <button
            key={p}
            onClick={() => { const d = datesForPreset(p); onChange(d.date_from, d.date_to) }}
            className={`px-2.5 py-1.5 ${activePreset === p ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
          >
            {presetLabels[p]}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-1">
        <input
          type="date"
          value={dateFrom}
          max={dateTo}
          onChange={e => onChange(e.target.value, dateTo)}
          className="border border-gray-200 rounded px-2 py-1 text-xs text-gray-700"
        />
        <span className="text-xs text-gray-400">–</span>
        <input
          type="date"
          value={dateTo}
          min={dateFrom}
          max={isoDate(new Date())}
          onChange={e => onChange(dateFrom, e.target.value)}
          className="border border-gray-200 rounded px-2 py-1 text-xs text-gray-700"
        />
      </div>
    </div>
  )
}

// ── Metric tile ───────────────────────────────────────────────────────────

function MetricTile({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="bg-gray-50 rounded-lg p-3 text-center">
      <p className="text-[11px] text-gray-500 uppercase tracking-wide mb-0.5">{label}</p>
      <p className={`text-sm font-semibold ${highlight ? 'text-blue-700' : 'text-gray-900'}`}>{value}</p>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function CampaignDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { user, loading: authLoading } = useAuth()
  const router = useRouter()

  // Shared date range — drives both the perf card and the ad group metrics table
  const [dateFrom, setDateFrom] = useState(defaultDateRange().date_from)
  const [dateTo, setDateTo] = useState(defaultDateRange().date_to)

  const [campaign, setCampaign] = useState<Campaign | null>(null)
  const [adGroups, setAdGroups] = useState<AdGroupWithMetrics[]>([])
  const [perfSummary, setPerfSummary] = useState<PerfMetrics | null>(null)
  const [perfNoData, setPerfNoData] = useState(false)
  const [search, setSearch] = useState('')
  const [dataLoading, setDataLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async (from: string, to: string) => {
    setDataLoading(true)
    setError(null)
    try {
      const [camp, groups, perf] = await Promise.all([
        api.getCampaign(id),
        api.getCampaignAdGroupsWithMetrics(id, { date_from: from, date_to: to }),
        api.getCampaignPerfSummary(id, { date_from: from, date_to: to }),
      ])
      setCampaign(camp)
      setAdGroups(groups)
      const hasData = perf && perf.impressions != null
      setPerfSummary(hasData ? perf : null)
      setPerfNoData(!hasData)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load campaign')
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

  const filteredAdGroups = useMemo(() =>
    adGroups.filter(ag => ag.name.toLowerCase().includes(search.toLowerCase())),
    [adGroups, search]
  )

  if (authLoading) return <LoadingState message="Checking authentication…" />
  if (!user) return null
  if (error) return <ErrorState message={error} onRetry={() => load(dateFrom, dateTo)} />
  if (dataLoading) return <LoadingState />
  if (!campaign) return null

  const agColumns: Column<AdGroupWithMetrics>[] = [
    {
      header: 'Ad Group',
      cell: row => <span className="font-medium text-gray-900">{row.name}</span>,
      sortValue: row => row.name,
    },
    {
      header: 'Status',
      cell: row => <StatusBadge status={row.status} />,
      sortValue: row => row.status,
    },
    {
      header: 'Spend',
      cell: row => (
        <span className={`text-sm ${row.spend != null ? 'text-gray-900 font-medium' : 'text-gray-400'}`}>
          {fmt.currency(row.spend)}
        </span>
      ),
      sortValue: row => row.spend ?? -1,
    },
    {
      header: 'Sales',
      cell: row => (
        <span className={`text-sm ${row.sales != null ? 'text-gray-900' : 'text-gray-400'}`}>
          {fmt.currency(row.sales)}
        </span>
      ),
      sortValue: row => row.sales ?? -1,
    },
    {
      header: 'ACOS',
      cell: row => {
        const v = row.acos != null ? Number(row.acos) : null
        const color = v == null ? 'text-gray-400' : v > 40 ? 'text-red-600' : v > 25 ? 'text-yellow-700' : 'text-green-600'
        return <span className={`text-sm font-medium ${color}`}>{fmt.acos(row.acos)}</span>
      },
      sortValue: row => row.acos ?? 9999,
    },
    {
      header: 'ROAS',
      cell: row => (
        <span className={`text-sm ${row.roas != null ? 'text-gray-900' : 'text-gray-400'}`}>
          {fmt.roas(row.roas)}
        </span>
      ),
      sortValue: row => row.roas ?? -1,
    },
    {
      header: 'Clicks',
      cell: row => <span className="text-sm text-gray-700">{fmt.int(row.clicks)}</span>,
      sortValue: row => row.clicks ?? -1,
    },
    {
      header: 'Default Bid',
      cell: row => (
        <span className="text-gray-600 text-sm">
          {row.default_bid != null ? `$${Number(row.default_bid).toFixed(2)}` : '—'}
        </span>
      ),
      sortValue: row => row.default_bid ?? 0,
    },
  ]

  return (
    <div>
      <button
        onClick={() => router.back()}
        className="text-sm text-blue-600 hover:underline mb-4 inline-block"
      >
        ← Back to Campaigns
      </button>
      <PageHeader
        title={campaign.name}
        subtitle={`${campaign.ad_product} · ${campaign.status}`}
        actions={<StatusBadge status={campaign.status} />}
      />

      {/* Campaign-level performance card — shares date range with ad groups table */}
      <div className="card mb-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-3">
          <h2 className="text-sm font-semibold text-gray-700">Performance</h2>
          <DateRangePicker dateFrom={dateFrom} dateTo={dateTo} onChange={handleDateChange} />
        </div>
        {dataLoading ? (
          <p className="text-xs text-gray-400 py-4 text-center">Loading metrics…</p>
        ) : perfNoData ? (
          <p className="text-xs text-gray-400 py-4 text-center">
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
        <h2 className="text-sm font-semibold text-gray-700 mb-2">Campaign Details</h2>
        <dl className="divide-y divide-gray-100">
          <DetailRow label="Type"    value={campaign.ad_product} />
          <DetailRow label="Status"  value={<StatusBadge status={campaign.status} />} />
          <DetailRow label="Targeting" value={campaign.targeting_type ?? '—'} />
          <DetailRow
            label="Daily Budget"
            value={campaign.daily_budget != null ? `$${Number(campaign.daily_budget).toFixed(2)}` : '—'}
          />
          <DetailRow label="Start Date" value={String(campaign.start_date ?? '—')} />
          <DetailRow label="End Date"   value={String(campaign.end_date ?? '—')} />
        </dl>
      </div>

      {/* Ad groups table — metrics match the same date range as the perf card above */}
      <div className="card">
        <div className="flex items-center justify-between mb-4 gap-3">
          <h2 className="text-sm font-semibold text-gray-700 shrink-0">
            Ad Groups ({filteredAdGroups.length}{search ? ` of ${adGroups.length}` : ''})
          </h2>
          <SearchBox
            value={search}
            onChange={setSearch}
            placeholder="Search ad groups…"
            className="max-w-xs w-full"
          />
        </div>
        <DataTable
          columns={agColumns}
          rows={filteredAdGroups}
          rowKey={r => r.id}
          onRowClick={r => router.push(`/ad-groups/${r.id}`)}
          rowHref={r => `/ad-groups/${r.id}`}
          resizeKey="campaign-detail-adgroups"
          emptyTitle="No ad groups"
          emptyDescription={search ? 'No ad groups match your search.' : 'No ad groups found for this campaign.'}
        />
      </div>
    </div>
  )
}

'use client'
/**
 * Dashboard — the "what needs my attention today" screen.
 *
 * The spec dropped a standalone Dashboard from MVP because Campaign Manager
 * carries a KPI strip, and the sidebar has said "Soon" ever since. This is
 * deliberately not another campaign table: it answers the questions a PPC
 * manager opens the app with — is the data current, what is my money doing,
 * what is losing money, and what is waiting for me.
 */
import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { api, ApiError } from '@/lib/api'
import type { CampaignWithMetrics, SyncJobRow, Suggestion, Anomaly } from '@/lib/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { StatBar } from '@/components/ui/StatBar'
import { LoadingState } from '@/components/ui/LoadingState'
import { ErrorState } from '@/components/ui/ErrorState'
import { fmt } from '@/components/ui/metricColumns'

/** Enough spend to make a ratio meaningful — below this ACOS is just noise. */
const MIN_SPEND_FOR_ACOS_ALERT = 1

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth()
  const { currentAccountId, currentProfileId, accountProfileIds, accountsLoading, profilesLoading } =
    useAccountProfile()
  const router = useRouter()

  const [campaigns, setCampaigns] = useState<CampaignWithMetrics[]>([])
  const [jobs, setJobs]           = useState<SyncJobRow[]>([])
  const [pending, setPending]     = useState<Suggestion[]>([])
  const [changeCount, setChangeCount] = useState(0)
  const [anomalies, setAnomalies] = useState<Anomaly[]>([])
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState<string | null>(null)

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async () => {
    if (!currentAccountId || profilesLoading) return
    setLoading(true); setError(null)
    try {
      const profileIds = currentProfileId ? [currentProfileId] : Array.from(accountProfileIds)
      const [camps, syncPage, suggestionBatches, changeRows, anomalyPage] = await Promise.all([
        api.getCampaignsWithMetrics(
          currentProfileId ? { profile_id: currentProfileId } : { account_id: currentAccountId },
        ),
        api.listSyncJobs({ limit: 20 }),
        // Suggestions are per-profile; "All Profiles" means asking each one.
        Promise.all(profileIds.map(pid => api.listSuggestions({ profile_id: pid, status: 'pending' }))),
        api.getChangeLog(currentProfileId ?? undefined, 1),
        // Anomalies are advisory: a failure here must not blank the whole
        // dashboard, so it degrades to an empty panel.
        api.getAnomalies(
          currentProfileId ? { profile_id: currentProfileId } : { account_id: currentAccountId },
        ).catch(() => ({ anomalies: [], checked_profiles: 0 })),
      ])
      setCampaigns(camps)
      setJobs(syncPage.jobs)
      setPending(suggestionBatches.flat())
      // The endpoint reports the true total, so the tile is exact rather
      // than "however many we happened to fetch".
      setChangeCount(changeRows.count)
      setAnomalies(anomalyPage.anomalies)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load dashboard')
    } finally {
      setLoading(false)
    }
  }, [currentAccountId, currentProfileId, accountProfileIds, profilesLoading])

  useEffect(() => {
    if (user && !accountsLoading && !profilesLoading && currentAccountId) load()
  }, [user, accountsLoading, profilesLoading, currentAccountId, load])

  const kpis = useMemo(() => {
    const n = (v: unknown) => (v == null ? 0 : Number(v))
    const spend  = campaigns.reduce((s, c) => s + n(c.spend), 0)
    const sales  = campaigns.reduce((s, c) => s + n(c.sales), 0)
    const orders = campaigns.reduce((s, c) => s + n(c.orders), 0)
    const clicks = campaigns.reduce((s, c) => s + n(c.clicks), 0)
    return {
      spend, sales, orders, clicks,
      // Undefined rather than zero when there are no sales — 0% ACOS would
      // read as spectacular rather than as "nothing sold".
      acos: sales > 0 ? (spend / sales) * 100 : null,
      roas: spend > 0 ? sales / spend : null,
      active: campaigns.filter(c => c.status === 'enabled').length,
    }
  }, [campaigns])

  const lastSuccess = useMemo(
    () => jobs.find(j => j.status === 'success' && j.finished_at),
    [jobs],
  )
  const hoursSinceSync = lastSuccess?.finished_at
    ? (Date.now() - new Date(lastSuccess.finished_at).getTime()) / 3600000
    : null
  const dataIsStale = hoursSinceSync == null || hoursSinceSync > 24

  const topSpenders = useMemo(
    () => [...campaigns].sort((a, b) => Number(b.spend ?? 0) - Number(a.spend ?? 0)).slice(0, 5),
    [campaigns],
  )

  /** Campaigns spending real money at bad or zero return — the actual to-do list. */
  const bleeding = useMemo(
    () => campaigns
      .filter(c => Number(c.spend ?? 0) >= MIN_SPEND_FOR_ACOS_ALERT)
      .filter(c => c.acos == null || Number(c.acos) > 40)
      .sort((a, b) => Number(b.spend ?? 0) - Number(a.spend ?? 0))
      .slice(0, 5),
    [campaigns],
  )

  if (authLoading || accountsLoading) return <LoadingState message="Loading…" />
  if (!user) return null
  if (error) return <ErrorState message={error} onRetry={load} />

  return (
    <div className="space-y-5">
      <PageHeader
        title="Dashboard"
        subtitle={loading ? 'Loading…' : 'Last 30 days'}
      />

      {/* Freshness first: every number below is only as good as the last sync. */}
      <button
        onClick={() => router.push('/sync-monitor')}
        className={`w-full text-left rounded-xl border p-3 transition-colors ${
          dataIsStale
            ? 'border-danger/20 bg-danger-tint hover:bg-danger-tint'
            : 'border-ok/20 bg-ok-tint hover:bg-ok-tint'
        }`}
      >
        <span className={`text-sm font-medium ${dataIsStale ? 'text-danger' : 'text-ok'}`}>
          {dataIsStale ? 'Data may be out of date' : 'Data is current'}
        </span>
        <span className={`text-sm ml-2 ${dataIsStale ? 'text-danger' : 'text-ok'}`}>
          {hoursSinceSync == null
            ? 'No sync has completed successfully yet.'
            : `Synced ${hoursSinceSync < 1 ? 'less than an hour' : `${Math.floor(hoursSinceSync)} hours`} ago.`}
          {' '}View sync monitor →
        </span>
      </button>

      {/* What changed — spec §13.1's anomaly panel. Above the KPI numbers on
          purpose: an average hides the campaign that broke yesterday. */}
      {anomalies.length > 0 && (
        <div className="rounded-xl border border-hairline bg-surface overflow-hidden">
          <div className="px-4 py-3 border-b border-hairline">
            <h2 className="font-semibold text-ink text-sm">Needs a look</h2>
            <p className="text-xs text-ink-muted mt-0.5">
              Campaigns that changed sharply in the last few days versus the two
              weeks before. Not threshold breaches — changes.
            </p>
          </div>
          <div className="divide-y divide-hairline">
            {anomalies.slice(0, 6).map((a, i) => (
              <button
                key={`${a.campaign_id}-${a.type}-${i}`}
                onClick={() => router.push(`/campaigns/${a.campaign_id}`)}
                className="w-full text-left px-4 py-3 hover:bg-surface-sunken flex items-start gap-3"
              >
                <span className={`mt-0.5 shrink-0 text-xs px-2 py-0.5 rounded font-medium ${
                  a.severity === 'high'
                    ? 'bg-danger-tint text-danger'
                    : 'bg-warn-tint text-warn'
                }`}>
                  {a.severity}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-ink truncate">
                    {a.headline}
                  </span>
                  <span className="block text-xs text-ink-muted truncate">
                    {a.campaign_name}
                    {a.marketplace && ` · ${a.marketplace}`}
                    {a.campaign_status !== 'enabled' && ` · ${a.campaign_status}`}
                  </span>
                  <span className="block text-xs text-ink-subtle mt-0.5">{a.detail}</span>
                </span>
              </button>
            ))}
          </div>
          {anomalies.length > 6 && (
            <p className="px-4 py-2 text-xs text-ink-subtle border-t border-hairline">
              {anomalies.length - 6} more not shown.
            </p>
          )}
        </div>
      )}

      {/* ACOS is the only figure here whose direction is good or bad on its own —
          spend of $45 is neither — so it is the only one that takes a tone. */}
      <StatBar
        stats={[
          { label: 'Spend',  value: fmt.currency(kpis.spend) },
          { label: 'Sales',  value: fmt.currency(kpis.sales) },
          { label: 'ACOS',   value: fmt.acos(kpis.acos),
            tone: kpis.acos == null ? undefined
              : kpis.acos > 40 ? 'danger' : kpis.acos > 25 ? 'warn' : 'ok' },
          { label: 'ROAS',   value: fmt.roas(kpis.roas) },
          { label: 'Orders', value: fmt.int(kpis.orders) },
          { label: 'Clicks', value: fmt.int(kpis.clicks) },
        ]}
      />

      {/* Waiting on a human */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <button
          onClick={() => router.push('/suggestions')}
          className="rounded-xl border border-hairline bg-surface p-4 text-left hover:border-accent-edge hover:bg-accent-weak/40 transition-colors"
        >
          <p className="text-xs text-ink-muted">Suggestions awaiting review</p>
          <p className="text-2xl font-bold text-ink mt-1">{pending.length}</p>
          <p className="text-xs text-accent mt-1">Open inbox →</p>
        </button>
        <div className="rounded-xl border border-hairline bg-surface p-4">
          <p className="text-xs text-ink-muted">Active campaigns</p>
          <p className="text-2xl font-bold text-ink mt-1">{kpis.active}</p>
          <p className="text-xs text-ink-subtle mt-1">of {campaigns.length} total</p>
        </div>
        <button
          onClick={() => router.push('/logs')}
          className="rounded-xl border border-hairline bg-surface p-4 text-left hover:border-accent-edge hover:bg-accent-weak/40 transition-colors"
        >
          <p className="text-xs text-ink-muted">Changes sent to Amazon</p>
          <p className="text-2xl font-bold text-ink mt-1">{changeCount}</p>
          <p className="text-xs text-accent mt-1">View log →</p>
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <CampaignList
          title="Where the money goes"
          subtitle="Highest spend, last 30 days"
          rows={topSpenders}
          loading={loading}
          empty="No campaign spend in this period."
          onClick={id => router.push(`/campaigns/${id}`)}
        />
        <CampaignList
          title="Needs attention"
          subtitle={`Spending over ${fmt.currency(MIN_SPEND_FOR_ACOS_ALERT)} with ACOS above 40% or no sales`}
          rows={bleeding}
          loading={loading}
          empty="Nothing is spending badly right now."
          onClick={id => router.push(`/campaigns/${id}`)}
        />
      </div>
    </div>
  )
}

function CampaignList({
  title, subtitle, rows, loading, empty, onClick,
}: {
  title: string
  subtitle: string
  rows: CampaignWithMetrics[]
  loading: boolean
  empty: string
  onClick: (id: string) => void
}) {
  return (
    <div className="card">
      <h2 className="font-semibold text-ink">{title}</h2>
      <p className="text-xs text-ink-muted mb-3">{subtitle}</p>
      {loading ? (
        <p className="text-sm text-ink-subtle py-6 text-center">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-ink-subtle py-6 text-center">{empty}</p>
      ) : (
        <div className="divide-y divide-hairline">
          {rows.map(c => (
            <button
              key={c.id}
              onClick={() => onClick(c.id)}
              className="w-full flex items-center justify-between gap-3 py-2.5 text-left hover:bg-surface-sunken -mx-2 px-2 rounded"
            >
              <span className="text-sm text-ink truncate flex-1" title={c.name}>{c.name}</span>
              <span className="text-sm font-medium text-ink shrink-0">{fmt.currency(c.spend)}</span>
              <span className={`text-sm shrink-0 w-16 text-right ${
                c.acos == null ? 'text-ink-subtle'
                  : Number(c.acos) > 40 ? 'text-danger'
                  : Number(c.acos) > 25 ? 'text-warn' : 'text-ok'
              }`}>
                {fmt.acos(c.acos)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

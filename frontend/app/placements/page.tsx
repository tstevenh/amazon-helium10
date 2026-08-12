'use client'
/**
 * Placements — where your ads actually appeared, and what each spot returned.
 *
 * Amazon lets you bid a multiplier per placement, so the question this answers
 * is "am I paying top-of-search prices for product-page results?". The totals
 * strip is the headline; the per-campaign table is for acting on it.
 */
import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { api, ApiError } from '@/lib/api'
import type { PlacementPage, PlacementMetrics } from '@/lib/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/ui/LoadingState'
import { ErrorState } from '@/components/ui/ErrorState'
import { fmt } from '@/components/ui/metricColumns'

/** Display order is the funnel order, not alphabetical or by spend. */
const PLACEMENT_ORDER = ['top_of_search', 'product_pages', 'rest_of_search', 'other']

const PLACEMENT_LABEL: Record<string, string> = {
  top_of_search:  'Top of search',
  product_pages:  'Product pages',
  rest_of_search: 'Rest of search',
  other:          'Unlabelled',
}

const PLACEMENT_HELP: Record<string, string> = {
  top_of_search:  'The first row of search results. Most expensive, usually highest intent.',
  product_pages:  'On other listings, below the fold. Cheaper clicks, more browsing.',
  rest_of_search: 'Anywhere else in search results.',
  other:          'Amazon returned these rows without a placement label.',
}

/** acos arrives as a RATIO from this endpoint — see the note in the repository. */
function acosPct(ratio: number | null): number | null {
  return ratio == null ? null : ratio * 100
}

export default function PlacementsPage() {
  const { user, loading: authLoading } = useAuth()
  const { currentAccountId, currentProfileId, accountsLoading, profilesLoading } =
    useAccountProfile()
  const router = useRouter()

  const [data, setData]       = useState<PlacementPage | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState<string | null>(null)

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async () => {
    if (!currentAccountId || profilesLoading) return
    setLoading(true); setError(null)
    try {
      setData(await api.getPlacements(
        currentProfileId ? { profile_id: currentProfileId } : { account_id: currentAccountId },
      ))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load placements')
    } finally {
      setLoading(false)
    }
  }, [currentAccountId, currentProfileId, profilesLoading])

  useEffect(() => {
    if (user && !accountsLoading && !profilesLoading) load()
  }, [user, accountsLoading, profilesLoading, load])

  const present = useMemo(
    () => PLACEMENT_ORDER.filter(p => data?.totals?.[p]),
    [data],
  )

  const grandSpend = useMemo(
    () => Object.values(data?.totals ?? {}).reduce((s, m) => s + (m.spend ?? 0), 0),
    [data],
  )

  if (authLoading || accountsLoading) return <LoadingState message="Loading…" />
  if (!user) return null
  if (error) return <ErrorState message={error} onRetry={load} />

  const hasData = present.length > 0

  return (
    <div className="space-y-4">
      <PageHeader
        title="Placements"
        subtitle={
          data?.date_from
            ? `Where your ads appeared · ${data.date_from} to ${data.date_to}`
            : 'Where your ads appeared'
        }
      />

      {loading && !data ? (
        <div className="card text-center py-12 text-gray-400">Loading…</div>
      ) : !hasData ? (
        <div className="card text-center py-14">
          <p className="text-gray-500 mb-1">No placement data yet</p>
          <p className="text-sm text-gray-400 max-w-md mx-auto">
            Placement figures come from a separate Amazon report that runs with the
            scheduled sync. It appears here after the next sync completes.
          </p>
        </div>
      ) : (
        <>
          {/* Totals — the headline. Share of spend is the number that prompts a
              decision, so it is shown rather than left to be worked out. */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
            {present.map(p => {
              const m = data!.totals[p]
              const share = grandSpend > 0 ? (m.spend / grandSpend) * 100 : 0
              const acos = m.acos == null ? null : Number(m.acos)
              return (
                <div key={p} className="rounded-xl border border-gray-200 bg-white p-4">
                  <p className="text-xs font-medium text-gray-700">{PLACEMENT_LABEL[p] ?? p}</p>
                  <p className="text-2xl font-bold text-gray-900 mt-1">{fmt.currency(m.spend)}</p>
                  <p className="text-xs text-gray-400">{share.toFixed(0)}% of spend</p>
                  <div className="mt-2 pt-2 border-t border-gray-100 space-y-0.5 text-xs">
                    <p className="flex justify-between">
                      <span className="text-gray-500">Sales</span>
                      <span className="text-gray-800">{fmt.currency(m.sales)}</span>
                    </p>
                    <p className="flex justify-between">
                      <span className="text-gray-500">ACOS</span>
                      <span className={
                        acos == null ? 'text-gray-400'
                          : acos > 40 ? 'text-red-600'
                          : acos > 25 ? 'text-yellow-700' : 'text-green-600'
                      }>
                        {/* totals.acos is already a percentage from the API */}
                        {acos == null ? '—' : `${acos.toFixed(1)}%`}
                      </span>
                    </p>
                    <p className="flex justify-between">
                      <span className="text-gray-500">Orders</span>
                      <span className="text-gray-800">{m.orders}</span>
                    </p>
                    <p className="flex justify-between">
                      <span className="text-gray-500">Clicks</span>
                      <span className="text-gray-800">{m.clicks}</span>
                    </p>
                  </div>
                  <p className="text-[11px] text-gray-400 mt-2">{PLACEMENT_HELP[p]}</p>
                </div>
              )
            })}
          </div>

          <div className="card p-0 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Campaign</th>
                  {present.map(p => (
                    <th key={p} className="px-4 py-3 text-right text-xs font-semibold text-gray-600">
                      {PLACEMENT_LABEL[p] ?? p}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data!.campaigns.map(row => (
                  <tr key={row.campaign_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <button
                        onClick={() => router.push(`/campaigns/${row.campaign_id}`)}
                        className="text-blue-600 hover:underline text-left truncate max-w-[240px] block"
                        title={row.campaign_name}
                      >
                        {row.campaign_name}
                      </button>
                    </td>
                    {present.map(p => {
                      const m: PlacementMetrics | undefined = row.placements[p]
                      if (!m) return <td key={p} className="px-4 py-3 text-right text-gray-300">—</td>
                      const pct = acosPct(m.acos)
                      return (
                        <td key={p} className="px-4 py-3 text-right">
                          <span className="text-gray-900">{fmt.currency(m.spend)}</span>
                          <span className={`block text-xs ${
                            pct == null ? 'text-gray-400'
                              : pct > 40 ? 'text-red-600'
                              : pct > 25 ? 'text-yellow-700' : 'text-green-600'
                          }`}>
                            {pct == null ? 'no sales' : `${pct.toFixed(0)}% ACOS`}
                          </span>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-xs text-gray-400">
            Amazon lets you bid a percentage more for a placement. A spot with low
            ACOS and little spend is usually worth bidding up; the reverse is worth
            bidding down. Adjustments are applied through an approved suggestion,
            never automatically.
          </p>
        </>
      )}
    </div>
  )
}

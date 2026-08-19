'use client'
import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { useUrlState } from '@/lib/useUrlState'
import { useAuth } from '@/context/AuthContext'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { api, ApiError } from '@/lib/api'
import type { TargetWithMetrics, AdGroup, Campaign } from '@/lib/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, Column, SortDir } from '@/components/ui/DataTable'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { SearchBox } from '@/components/ui/SearchBox'
import { FilterBar, FilterConfig } from '@/components/ui/FilterBar'
import { LoadingState } from '@/components/ui/LoadingState'
import { ErrorState } from '@/components/ui/ErrorState'
import { EmptyState } from '@/components/ui/EmptyState'
import { emptyDataMessage } from '@/lib/emptyState'
import { metricColumns } from '@/components/ui/metricColumns'

const LIMIT = 2000

// Module scope on purpose: useUrlState memoises on this object's identity.
// `sort` stores a column HEADER rather than an index so reordering columns
// cannot silently change what a saved link sorts by.
const KEYWORD_FILTER_DEFAULTS = {
  search: '',
  status: 'all',
  match: 'all',
  sort: 'Spend',
  dir: 'desc',
}

export default function KeywordsPage() {
  const { user, loading: authLoading } = useAuth()
  const {
    currentAccountId,
    currentProfileId,
    currentAccount,
    accountProfileIds,
    accountsLoading,
    profilesLoading, profileCounts, setCurrentProfile } = useAccountProfile()
  const router = useRouter()

  const [keywords, setKeywords] = useState<TargetWithMetrics[]>([])
  const [adGroups, setAdGroups] = useState<AdGroup[]>([])
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  // Filters live in the URL, not useState: pressing Back from a keyword used
  // to remount this screen with its defaults and silently discard the
  // operator's filters. See lib/useUrlState.ts.
  const [urlState, setUrlState] = useUrlState(KEYWORD_FILTER_DEFAULTS)
  const { search, status: statusFilter, match: matchFilter } = urlState
  const setSearch = (v: string) => setUrlState({ search: v })
  const setStatusFilter = (v: string) => setUrlState({ status: v })
  const setMatchFilter = (v: string) => setUrlState({ match: v })
  const [dataLoading, setDataLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [totalKeywords, setTotalKeywords] = useState(0)

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async () => {
    if (!currentAccountId) return
    setDataLoading(true)
    setError(null)
    setKeywords([])
    try {
      // Ranked by spend server-side. The old call was a bare LIMIT with no
      // ORDER BY, so the 2,000 rows shown were an arbitrary slice of 219,285
      // — overwhelmingly zero-traffic keywords, which is why this screen
      // looked empty. Now the cap keeps the keywords that cost money.
      const [kwPage, ags, camps] = await Promise.all([
        api.listTargetsWithMetrics({
          target_kind: 'keyword',
          limit: LIMIT,
          ...(currentProfileId
            ? { profile_id: currentProfileId }
            : { account_id: currentAccountId }),
        }),
        api.listAdGroups(currentProfileId ? { profile_id: currentProfileId } : undefined),
        api.listCampaigns(),
      ])
      setKeywords(kwPage.items)
      setTotalKeywords(kwPage.total)
      setAdGroups(ags)
      setCampaigns(camps)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load keywords')
    } finally {
      setDataLoading(false)
    }
  }, [currentAccountId, currentProfileId])

  useEffect(() => {
    if (user && !accountsLoading && currentAccountId) load()
  }, [user, accountsLoading, currentAccountId, load])

  const adGroupMap = useMemo<Record<string, AdGroup>>(() => {
    const m: Record<string, AdGroup> = {}
    adGroups.forEach(ag => { m[ag.id] = ag })
    return m
  }, [adGroups])

  const campaignMap = useMemo<Record<string, Campaign>>(() => {
    const m: Record<string, Campaign> = {}
    campaigns.forEach(c => { m[c.id] = c })
    return m
  }, [campaigns])

  const filtered = useMemo(() => keywords.filter(kw => {
    const ag = adGroupMap[kw.ad_group_id]
    const camp = ag ? campaignMap[ag.campaign_id] : undefined
    const text = kw.expression_text?.toLowerCase() ?? ''
    const agName = ag?.name.toLowerCase() ?? ''
    const campName = camp?.name.toLowerCase() ?? ''
    const q = search.toLowerCase()
    const matchSearch = !q || text.includes(q) || agName.includes(q) || campName.includes(q)
    const matchStatus = statusFilter === 'all' || kw.status === statusFilter
    const matchMatch = matchFilter === 'all' || kw.match_type === matchFilter
    return matchSearch && matchStatus && matchMatch
  }), [keywords, search, statusFilter, matchFilter, adGroupMap, campaignMap])

  if (authLoading || accountsLoading) return <LoadingState message="Loading…" />
  if (!user) return null
  if (error) return <ErrorState message={error} onRetry={load} />
  if (!currentAccountId) return (
    <EmptyState title="No account selected" description="Use the Account selector in the header." />
  )

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
      key: 'match', label: 'Match Type', value: matchFilter, onChange: setMatchFilter,
      options: [
        { value: 'all', label: 'All Match Types' },
        { value: 'exact', label: 'Exact' },
        { value: 'phrase', label: 'Phrase' },
        { value: 'broad', label: 'Broad' },
      ],
    },
  ]

  const columns: Column<TargetWithMetrics>[] = [
    {
      header: 'Keyword',
      cell: row => <span className="font-medium text-ink">{row.expression_text || '—'}</span>,
      sortValue: row => row.expression_text ?? '',
    },
    {
      header: 'Match Type',
      cell: row => (
        <span className="text-xs font-mono bg-surface-sunken rounded px-2 py-0.5 capitalize">
          {row.match_type ?? '—'}
        </span>
      ),
      sortValue: row => row.match_type ?? '',
    },
    {
      header: 'Status',
      cell: row => <StatusBadge status={row.status} />,
      sortValue: row => row.status,
    },
    {
      header: 'Bid',
      cell: row => (
        <span className="text-ink">
          {row.bid != null ? `$${Number(row.bid).toFixed(2)}` : '—'}
        </span>
      ),
      sortValue: row => row.bid ?? 0,
    },
    {
      header: 'Ad Group',
      cell: row => {
        const ag = adGroupMap[row.ad_group_id]
        return ag ? (
          <button
            onClick={e => { e.stopPropagation(); router.push(`/ad-groups/${ag.id}`) }}
            className="text-accent hover:underline text-sm text-left"
          >
            {ag.name}
          </button>
        ) : <span className="text-ink-subtle text-sm">—</span>
      },
      sortValue: row => adGroupMap[row.ad_group_id]?.name ?? '',
    },
    {
      header: 'Campaign',
      cell: row => {
        const ag = adGroupMap[row.ad_group_id]
        const camp = ag ? campaignMap[ag.campaign_id] : undefined
        return camp ? (
          <button
            onClick={e => { e.stopPropagation(); router.push(`/campaigns/${camp.id}`) }}
            className="text-accent hover:underline text-sm text-left"
          >
            {camp.name}
          </button>
        ) : <span className="text-ink-subtle text-sm">—</span>
      },
      sortValue: row => {
        const ag = adGroupMap[row.ad_group_id]
        return ag ? campaignMap[ag.campaign_id]?.name ?? '' : ''
      },
    },
    ...metricColumns<TargetWithMetrics>(),
  ]

  // Plain computation, deliberately not useMemo: this sits after the early
  // returns above, so a hook here would run on some renders and not others.
  const sortColFound = columns.findIndex(c => c.header === urlState.sort)
  const sortCol =
    sortColFound >= 0 ? sortColFound : columns.findIndex(c => c.header === 'Spend')
  const sortDir: SortDir = urlState.dir === 'asc' ? 'asc' : 'desc'

  const isLoading = dataLoading || profilesLoading
  const accountLabel = currentAccount?.name ?? 'this account'

  return (
    <div>
      <PageHeader
        title="Keywords"
        subtitle={
          isLoading
            ? 'Loading…'
            : `${filtered.length} of ${keywords.length} keyword${keywords.length !== 1 ? 's' : ''} shown`
        }
      />
      {totalKeywords > keywords.length && (
        <div className="mb-4 px-4 py-2 bg-accent-weak border border-accent-edge rounded text-sm text-accent">
          Showing the top {keywords.length.toLocaleString()} keywords by spend, out of{' '}
          {totalKeywords.toLocaleString()}. The rest spent nothing over this period.
          {/* The old copy said "use the search box to find specific keywords",
              which was untrue: search only filters the rows already loaded. */}
        </div>
      )}
      <div className="card">
        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          <SearchBox
            value={search}
            onChange={setSearch}
            placeholder="Search keywords, ad groups, or campaigns…"
            className="flex-1"
          />
          <FilterBar filters={filters} />
        </div>
        <DataTable
          columns={columns}
          rows={filtered}
          resizeKey="keywords"
          sortCol={sortCol}
          sortDir={sortDir}
          onSortChange={(col, dir) =>
            setUrlState({ sort: col === null ? '' : columns[col].header, dir })
          }
          rowKey={r => r.id}
          loading={isLoading}
          emptyTitle="No keywords found"
          emptyDescription={
            accountProfileIds.size === 0
              ? `No profiles synced for ${accountLabel}. Run Sync All from Settings → Accounts.`
              : emptyDataMessage({ entity: 'keywords', profileCounts,
                                   currentProfileId, accountName: accountLabel }).message
          }
        />
      </div>
    </div>
  )
}

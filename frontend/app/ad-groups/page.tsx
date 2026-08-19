'use client'
import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { useUrlState } from '@/lib/useUrlState'
import { useAuth } from '@/context/AuthContext'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { api, ApiError } from '@/lib/api'
import type { AdGroupWithMetrics, Campaign } from '@/lib/types'
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

// Module scope on purpose: useUrlState memoises on this object's identity.
// `sort` stores a column HEADER rather than an index so reordering columns
// cannot silently change what a saved link sorts by.
const AD_GROUP_FILTER_DEFAULTS = {
  search: '',
  status: 'all',
  sort: 'Spend',
  dir: 'desc',
}

export default function AdGroupsPage() {
  const { user, loading: authLoading } = useAuth()
  const {
    currentAccountId,
    currentProfileId,
    currentAccount,
    accountProfileIds,
    accountsLoading,
    profilesLoading, profileCounts, setCurrentProfile } = useAccountProfile()
  const router = useRouter()

  const [adGroups, setAdGroups] = useState<AdGroupWithMetrics[]>([])
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  // Filters live in the URL, not useState — see lib/useUrlState.ts for why.
  const [urlState, setUrlState] = useUrlState(AD_GROUP_FILTER_DEFAULTS)
  const { search, status: statusFilter } = urlState
  const setSearch = (v: string) => setUrlState({ search: v })
  const setStatusFilter = (v: string) => setUrlState({ status: v })
  const [dataLoading, setDataLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async () => {
    if (!currentAccountId) return
    setDataLoading(true)
    setError(null)
    setAdGroups([])
    try {
      // Metrics endpoint, not the bare list: an ad group without spend,
      // sales and ACOS tells a PPC manager nothing about what to do next.
      const [ags, camps] = await Promise.all([
        api.listAdGroupsWithMetrics(
          currentProfileId
            ? { profile_id: currentProfileId }
            : { account_id: currentAccountId },
        ),
        api.listCampaigns(),
      ])
      setAdGroups(ags)
      setCampaigns(camps)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load ad groups')
    } finally {
      setDataLoading(false)
    }
  }, [currentAccountId, currentProfileId])

  useEffect(() => {
    if (user && !accountsLoading && currentAccountId) load()
  }, [user, accountsLoading, currentAccountId, load])

  // campaign UUID → Campaign lookup
  const campaignMap = useMemo<Record<string, Campaign>>(() => {
    const m: Record<string, Campaign> = {}
    campaigns.forEach(c => { m[c.id] = c })
    return m
  }, [campaigns])

  // Filter by account/profile using campaign's profile_id
  const contextFiltered = useMemo(() => {
    if (!currentAccountId || profilesLoading) return []
    return adGroups.filter(ag => {
      const camp = campaignMap[ag.campaign_id]
      if (!camp) return false
      if (currentProfileId) return camp.profile_id === currentProfileId
      return accountProfileIds.has(camp.profile_id)
    })
  }, [adGroups, campaignMap, currentAccountId, currentProfileId, accountProfileIds, profilesLoading])

  const filtered = useMemo(() => contextFiltered.filter(ag => {
    const matchSearch = ag.name.toLowerCase().includes(search.toLowerCase()) ||
      (campaignMap[ag.campaign_id]?.name ?? '').toLowerCase().includes(search.toLowerCase())
    const matchStatus = statusFilter === 'all' || ag.status === statusFilter
    return matchSearch && matchStatus
  }), [contextFiltered, search, statusFilter, campaignMap])

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
  ]

  const columns: Column<AdGroupWithMetrics>[] = [
    {
      header: 'Ad Group',
      cell: row => <span className="font-medium text-ink">{row.name}</span>,
      sortValue: row => row.name,
    },
    {
      header: 'Campaign',
      cell: row => {
        const c = campaignMap[row.campaign_id]
        return c ? (
          <button
            onClick={e => { e.stopPropagation(); router.push(`/campaigns/${c.id}`) }}
            className="text-accent hover:underline text-sm text-left"
          >
            {c.name}
          </button>
        ) : <span className="text-ink-subtle text-sm">—</span>
      },
      sortValue: row => campaignMap[row.campaign_id]?.name ?? '',
    },
    {
      header: 'Type',
      cell: row => {
        const c = campaignMap[row.campaign_id]
        return c ? (
          <span className="text-xs font-mono bg-surface-sunken rounded px-2 py-0.5">{c.ad_product}</span>
        ) : <span className="text-ink-subtle">—</span>
      },
    },
    {
      header: 'Status',
      cell: row => <StatusBadge status={row.status} />,
      sortValue: row => row.status,
    },
    {
      header: 'Default Bid',
      cell: row => (
        <span className="text-ink">
          {row.default_bid != null ? `$${Number(row.default_bid).toFixed(2)}` : '—'}
        </span>
      ),
      sortValue: row => row.default_bid ?? 0,
    },
    ...metricColumns<AdGroupWithMetrics>(),
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
        title="Ad Groups"
        subtitle={
          isLoading
            ? 'Loading…'
            : `${filtered.length} of ${contextFiltered.length} ad group${contextFiltered.length !== 1 ? 's' : ''}`
        }
      />
      <div className="card">
        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          <SearchBox
            value={search}
            onChange={setSearch}
            placeholder="Search ad groups or campaigns…"
            className="flex-1"
          />
          <FilterBar filters={filters} />
        </div>
        <DataTable
          columns={columns}
          rows={filtered}
          sortCol={sortCol}
          sortDir={sortDir}
          onSortChange={(col, dir) =>
            setUrlState({ sort: col === null ? '' : columns[col].header, dir })
          }
          rowKey={r => r.id}
          onRowClick={r => router.push(`/ad-groups/${r.id}`)}
          rowHref={r => `/ad-groups/${r.id}`}
          resizeKey="ad-groups"
          loading={isLoading}
          emptyTitle="No ad groups found"
          emptyDescription={
            accountProfileIds.size === 0
              ? `No profiles synced for ${accountLabel}. Run Sync All from Settings → Accounts.`
              : emptyDataMessage({ entity: 'ad groups', profileCounts,
                                   currentProfileId, accountName: accountLabel }).message
          }
        />
      </div>
    </div>
  )
}

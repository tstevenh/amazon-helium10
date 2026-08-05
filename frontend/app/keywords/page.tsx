'use client'
import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { api, ApiError } from '@/lib/api'
import type { Target, AdGroup, Campaign } from '@/lib/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { DataTable, Column } from '@/components/ui/DataTable'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { SearchBox } from '@/components/ui/SearchBox'
import { FilterBar, FilterConfig } from '@/components/ui/FilterBar'
import { LoadingState } from '@/components/ui/LoadingState'
import { ErrorState } from '@/components/ui/ErrorState'
import { EmptyState } from '@/components/ui/EmptyState'

const LIMIT = 2000

export default function KeywordsPage() {
  const { user, loading: authLoading } = useAuth()
  const {
    currentAccountId,
    currentProfileId,
    currentAccount,
    accountProfileIds,
    accountsLoading,
    profilesLoading,
  } = useAccountProfile()
  const router = useRouter()

  const [keywords, setKeywords] = useState<Target[]>([])
  const [adGroups, setAdGroups] = useState<AdGroup[]>([])
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [matchFilter, setMatchFilter] = useState('all')
  const [dataLoading, setDataLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [wasCapped, setWasCapped] = useState(false)

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async () => {
    if (!currentAccountId) return
    setDataLoading(true)
    setError(null)
    setKeywords([])
    try {
      const params: Parameters<typeof api.listTargets>[0] = {
        target_kind: 'keyword',
        limit: LIMIT,
      }
      if (currentProfileId) params.profile_id = currentProfileId
      const [kws, ags, camps] = await Promise.all([
        api.listTargets(params),
        api.listAdGroups(currentProfileId ? { profile_id: currentProfileId } : undefined),
        api.listCampaigns(),
      ])
      setKeywords(kws)
      setWasCapped(kws.length >= LIMIT)
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

  const columns: Column<Target>[] = [
    {
      header: 'Keyword',
      cell: row => <span className="font-medium text-gray-900">{row.expression_text || '—'}</span>,
      sortValue: row => row.expression_text ?? '',
    },
    {
      header: 'Match Type',
      cell: row => (
        <span className="text-xs font-mono bg-gray-100 rounded px-2 py-0.5 capitalize">
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
        <span className="text-gray-700">
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
            className="text-blue-600 hover:underline text-sm text-left"
          >
            {ag.name}
          </button>
        ) : <span className="text-gray-400 text-sm">—</span>
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
            className="text-blue-600 hover:underline text-sm text-left"
          >
            {camp.name}
          </button>
        ) : <span className="text-gray-400 text-sm">—</span>
      },
      sortValue: row => {
        const ag = adGroupMap[row.ad_group_id]
        return ag ? campaignMap[ag.campaign_id]?.name ?? '' : ''
      },
    },
  ]

  const isLoading = dataLoading || profilesLoading
  const accountLabel = currentAccount?.name ?? 'this account'

  return (
    <div>
      <PageHeader
        title="Keywords"
        subtitle={
          isLoading
            ? 'Loading…'
            : `${filtered.length} of ${keywords.length} keyword${keywords.length !== 1 ? 's' : ''}`
        }
      />
      {wasCapped && (
        <div className="mb-4 px-4 py-2 bg-yellow-50 border border-yellow-200 rounded text-sm text-yellow-800">
          Showing first {LIMIT.toLocaleString()} keywords. Your account has more — use the search box to find specific keywords.
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
          rowKey={r => r.id}
          loading={isLoading}
          emptyTitle="No keywords found"
          emptyDescription={
            accountProfileIds.size === 0
              ? `No profiles synced for ${accountLabel}. Run Sync All from Settings → Accounts.`
              : `No keywords found for ${accountLabel}. Run Sync All from Settings → Accounts.`
          }
        />
      </div>
    </div>
  )
}

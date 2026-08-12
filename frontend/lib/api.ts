/**
 * API client for PPC OS backend.
 * Token is read automatically from local storage — callers do not pass it.
 * Only login() and me() are unauthenticated / use an explicit token.
 *
 * Sync calls (syncCampaigns, syncAdGroups, syncTargets, syncAll) use
 * syncRequest() which routes through the Next.js Route Handler at
 * /api/proxy-sync/... instead of the rewrite proxy at /backend/...
 * The Route Handler has no proxy timeout, avoiding the ~30 s limit that
 * kills long-running Amazon sync operations.
 */
import type {
  Account, AccountDetail, AdGroup, BulkResolveResponse, Campaign,
  ConnectionTestResponse, ExecuteRuleResponse, GenerateResponse,
  ChangeLogResponse, OAuthStartResponse, Profile, ProfileCount, Rule, RuleExecution,
  SearchTermRow, SuggestionActionEntry,
  SearchTermSyncResponse, Suggestion, SyncAllResponse, SyncResult, SyncStatus,
  Target, TokenResponse, User,
} from './types'

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// Sync calls go through the Next.js Route Handler (no proxy timeout).
// This path is always relative — it hits the Next.js dev server itself,
// which then forwards to http://api:8000 with a 3-minute Node.js timeout.
const SYNC_BASE = '/api/proxy-sync'

const TOKEN_KEY = 'ppc_os_token'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Read stored auth token (client only). Returns null during SSR or if unset. */
function getStoredToken(): string | null {
  return typeof window !== 'undefined' ? localStorage.getItem(TOKEN_KEY) : null
}

export function storeToken(token: string) {
  if (typeof window !== 'undefined') localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  if (typeof window !== 'undefined') localStorage.removeItem(TOKEN_KEY)
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  explicitToken?: string | null,
): Promise<T> {
  const token = explicitToken !== undefined ? explicitToken : getStoredToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
  const res = await fetch(`${BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, body.detail ?? 'Request failed')
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

/**
 * Like request() but routes through /api/proxy-sync/... (Route Handler)
 * instead of /backend/... (rewrite proxy).  Use for any POST that may
 * take longer than ~30 s (all Amazon sync endpoints).
 */
async function syncRequest<T>(path: string): Promise<T> {
  const token = getStoredToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
  const res = await fetch(`${SYNC_BASE}${path}`, { method: 'POST', headers })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, body.detail ?? 'Request failed')
  }
  return res.json()
}

export const api = {
  // ── Auth ────────────────────────────────────────────────────────────────
  login: (email: string, password: string) =>
    request<TokenResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }, null),

  me: () => request<User>('/auth/me'),

  // ── Accounts ────────────────────────────────────────────────────────────
  listAccounts: () =>
    request<Account[]>('/accounts'),

  createAccount: (name: string) =>
    request<AccountDetail>('/accounts', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),

  getAccount: (id: string) =>
    request<AccountDetail>(`/accounts/${id}`),

  /** Campaign counts per marketplace — lets the UI say WHERE the data is
   *  instead of telling an operator to run a sync that changes nothing. */
  // ── Execution audit (Plan 3) ────────────────────────────────────────
  /** What actually changed on Amazon, newest first. */
  getChangeLog: (profileId?: string, limit = 200) =>
    request<ChangeLogResponse>(
      `/change-log?limit=${limit}` + (profileId ? `&profile_id=${profileId}` : ''),
    ),

  /** Undo one executed change by writing its old value back to Amazon. */
  rollbackChange: (changeId: string) =>
    request<{ ok: boolean; change_id: string; detail: string }>(
      `/change-log/${changeId}/rollback`, { method: 'POST' },
    ),

  /** Every execution attempt for a suggestion, with the Amazon exchange. */
  getSuggestionActions: (suggestionId: string) =>
    request<{ suggestion_id: string; actions: SuggestionActionEntry[] }>(
      `/suggestions/${suggestionId}/actions`,
    ),

  /** Apply an approved suggestion to Amazon. Admin only; returns 202. */
  executeSuggestion: (suggestionId: string) =>
    request<{ message: string; suggestion_id: string; status: string }>(
      `/suggestions/${suggestionId}/execute`, { method: 'POST' },
    ),

  getProfileCounts: (accountId: string) =>
    request<ProfileCount[]>(`/accounts/${accountId}/profile-counts`),

  getProfiles: (accountId: string) =>
    request<Profile[]>(`/accounts/${accountId}/profiles`),

  syncProfiles: (accountId: string) =>
    request<{ message: string; seller_account_id: string; profiles_synced: number }>(
      `/accounts/${accountId}/profiles/sync`,
      { method: 'POST' },
    ),

  oauthStart: (accountId: string) =>
    request<OAuthStartResponse>(`/accounts/${accountId}/oauth/start`),

  /** Sprint 3.5: Run 4-step Amazon Ads connection diagnostic. */
  connectionTest: (accountId: string) =>
    request<ConnectionTestResponse>(`/accounts/${accountId}/connection-test`),

  /** Sprint 4: DB counts loaded on page mount (shows sync result after navigation). */
  getSyncStatus: (accountId: string) =>
    request<SyncStatus>(`/accounts/${accountId}/sync-status`),

  // ── Campaign sync (via Route Handler — no proxy timeout) ─────────────
  syncCampaigns: (accountId: string) =>
    syncRequest<{ message: string; seller_account_id: string; campaigns: SyncResult }>(
      `/accounts/${accountId}/campaigns/sync`,
    ),

  syncAdGroups: (accountId: string) =>
    syncRequest<{ message: string; seller_account_id: string; ad_groups: SyncResult }>(
      `/accounts/${accountId}/ad-groups/sync`,
    ),

  syncTargets: (accountId: string) =>
    syncRequest<{ message: string; seller_account_id: string; targets: SyncResult }>(
      `/accounts/${accountId}/targets/sync`,
    ),

  /** Full sync. perfDays omitted = routine 3-day rolling window (90 days
   *  automatically on a profile's first sync). 90 is a slow backfill. */
  syncAll: (accountId: string, perfDays?: number) =>
    syncRequest<SyncAllResponse>(
      `/accounts/${accountId}/sync-all` + (perfDays ? `?perf_days=${perfDays}` : ''),
    ),

  // ── Campaigns ────────────────────────────────────────────────────────────
  listCampaigns: (params?: { include_deleted?: boolean }) => {
    const qs = new URLSearchParams()
    if (params?.include_deleted) qs.set('include_deleted', 'true')
    const q = qs.toString() ? `?${qs}` : ''
    return request<Campaign[]>(`/campaigns${q}`)
  },

  getCampaign: (id: string) =>
    request<Campaign>(`/campaigns/${id}`),

  getCampaignAdGroups: (campaignId: string) =>
    request<AdGroup[]>(`/campaigns/${campaignId}/ad-groups`),

  // ── Ad Groups ────────────────────────────────────────────────────────────
  listAdGroups: (params?: { profile_id?: string; include_deleted?: boolean }) => {
    const qs = new URLSearchParams()
    if (params?.profile_id) qs.set('profile_id', params.profile_id)
    if (params?.include_deleted) qs.set('include_deleted', 'true')
    const q = qs.toString() ? `?${qs}` : ''
    return request<AdGroup[]>(`/ad-groups${q}`)
  },

  getAdGroup: (id: string) =>
    request<AdGroup>(`/ad-groups/${id}`),

  // ── Targets ──────────────────────────────────────────────────────────────
  listTargets: (params?: { target_kind?: string; ad_group_id?: string; profile_id?: string; limit?: number }) => {
    const qs = new URLSearchParams()
    if (params?.target_kind) qs.set('target_kind', params.target_kind)
    if (params?.ad_group_id) qs.set('ad_group_id', params.ad_group_id)
    if (params?.profile_id)  qs.set('profile_id',  params.profile_id)
    if (params?.limit != null) qs.set('limit', String(params.limit))
    const q = qs.toString() ? `?${qs}` : ''
    return request<Target[]>(`/targets${q}`)
  },

  getTarget: (id: string) =>
    request<Target>(`/targets/${id}`),

  // ── Sprint 2: Search Terms ────────────────────────────────────────────
  listSearchTerms: (params: {
    profile_id: string
    date_from?: string
    date_to?: string
    campaign_id?: string
    min_spend?: number
    min_sales?: number
    max_acos?: number
    q?: string
  }) => {
    const qs = new URLSearchParams()
    qs.set('profile_id', params.profile_id)
    if (params.date_from)   qs.set('date_from',   params.date_from)
    if (params.date_to)     qs.set('date_to',     params.date_to)
    if (params.campaign_id) qs.set('campaign_id', params.campaign_id)
    if (params.min_spend != null) qs.set('min_spend', String(params.min_spend))
    if (params.min_sales != null) qs.set('min_sales', String(params.min_sales))
    if (params.max_acos  != null) qs.set('max_acos',  String(params.max_acos))
    if (params.q)           qs.set('q', params.q)
    return request<SearchTermRow[]>(`/search-terms?${qs}`)
  },

  syncSearchTerms: (accountId: string) =>
    request<SearchTermSyncResponse>(`/accounts/${accountId}/search-terms/sync`, { method: 'POST' }),

  // ── Sprint 2 / 2.5: Suggestions ──────────────────────────────────────
  listSuggestions: (params: {
    profile_id: string
    status?: string
    kind?: string
    confidence_min?: number
    confidence_max?: number
    sort_by?: string
  }) => {
    const qs = new URLSearchParams()
    qs.set('profile_id', params.profile_id)
    if (params.status)         qs.set('status',         params.status)
    if (params.kind)           qs.set('kind',           params.kind)
    if (params.confidence_min != null) qs.set('confidence_min', String(params.confidence_min))
    if (params.confidence_max != null) qs.set('confidence_max', String(params.confidence_max))
    if (params.sort_by)        qs.set('sort_by',        params.sort_by)
    return request<Suggestion[]>(`/suggestions?${qs}`)
  },

  generateSuggestions: (profileId: string) =>
    request<GenerateResponse>(`/suggestions/generate?profile_id=${profileId}`, { method: 'POST' }),

  approveSuggestion: (id: string, reason?: string) =>
    request<Suggestion>(`/suggestions/${id}/approve`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason ?? null }),
    }),

  rejectSuggestion: (id: string, reason?: string) =>
    request<Suggestion>(`/suggestions/${id}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason ?? null }),
    }),

  bulkApproveSuggestions: (ids: string[], reason?: string) =>
    request<BulkResolveResponse>('/suggestions/bulk-approve', {
      method: 'POST',
      body: JSON.stringify({ ids, reason: reason ?? null }),
    }),

  bulkRejectSuggestions: (ids: string[], reason?: string) =>
    request<BulkResolveResponse>('/suggestions/bulk-reject', {
      method: 'POST',
      body: JSON.stringify({ ids, reason: reason ?? null }),
    }),

  // ── Sprint 3: Rules Engine ────────────────────────────────────────────
  listRules: (profileId: string, includeDisabled = true) => {
    const qs = new URLSearchParams()
    qs.set('profile_id', profileId)
    qs.set('include_disabled', String(includeDisabled))
    return request<Rule[]>(`/rules?${qs}`)
  },

  createRule: (data: {
    profile_id: string
    name: string
    description?: string | null
    rule_type: string
    status?: string
    configuration_json: Record<string, unknown>
  }) =>
    request<Rule>('/rules', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  getRule: (id: string) =>
    request<Rule>(`/rules/${id}`),

  updateRule: (id: string, data: {
    name?: string
    description?: string | null
    rule_type?: string
    status?: string
    configuration_json?: Record<string, unknown>
  }) =>
    request<Rule>(`/rules/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  deleteRule: (id: string) =>
    request<void>(`/rules/${id}`, { method: 'DELETE' }),

  cloneRule: (id: string) =>
    request<Rule>(`/rules/${id}/clone`, { method: 'POST' }),

  enableRule: (id: string) =>
    request<Rule>(`/rules/${id}/enable`, { method: 'POST' }),

  disableRule: (id: string) =>
    request<Rule>(`/rules/${id}/disable`, { method: 'POST' }),

  executeRule: (id: string) =>
    request<ExecuteRuleResponse>(`/rules/${id}/execute`, { method: 'POST' }),

  getRuleExecutions: (id: string, limit = 10) =>
    request<RuleExecution[]>(`/rules/${id}/executions?limit=${limit}`),


  // ── Performance metrics (Sprint 4B) ─────────────────────────
  getCampaignsWithMetrics: (params: {
    date_from?: string
    date_to?: string
    profile_id?: string
    account_id?: string
  }) => {
    const qs = new URLSearchParams()
    if (params.date_from) qs.set('date_from', params.date_from)
    if (params.date_to) qs.set('date_to', params.date_to)
    if (params.profile_id) qs.set('profile_id', params.profile_id)
    if (params.account_id) qs.set('account_id', params.account_id)
    return request<import('./types').CampaignWithMetrics[]>(`/performance/campaigns?${qs}`)
  },

  getCampaignPerfSummary: (campaignId: string, params: { date_from?: string; date_to?: string }) => {
    const qs = new URLSearchParams()
    if (params.date_from) qs.set('date_from', params.date_from)
    if (params.date_to) qs.set('date_to', params.date_to)
    return request<import('./types').PerfMetrics>(`/performance/campaigns/${campaignId}/summary?${qs}`)
  },

  getAdGroupPerfSummary: (adGroupId: string, params: { date_from?: string; date_to?: string }) => {
    const qs = new URLSearchParams()
    if (params.date_from) qs.set('date_from', params.date_from)
    if (params.date_to) qs.set('date_to', params.date_to)
    return request<import('./types').PerfMetrics>(`/performance/ad-groups/${adGroupId}/summary?${qs}`)
  },

  getCampaignAdGroupsWithMetrics: (campaignId: string, params: { date_from?: string; date_to?: string }) => {
    const qs = new URLSearchParams()
    if (params.date_from) qs.set('date_from', params.date_from)
    if (params.date_to) qs.set('date_to', params.date_to)
    return request<import('./types').AdGroupWithMetrics[]>(`/performance/campaigns/${campaignId}/ad-groups?${qs}`)
  },

  getAdGroupTargetsWithMetrics: (adGroupId: string, params: { date_from?: string; date_to?: string }) => {
    const qs = new URLSearchParams()
    if (params.date_from) qs.set('date_from', params.date_from)
    if (params.date_to) qs.set('date_to', params.date_to)
    return request<import('./types').TargetWithMetrics[]>(`/performance/ad-groups/${adGroupId}/targets?${qs}`)
  },

  /** Ad groups across a profile/account, highest spend first. */
  listAdGroupsWithMetrics: (params: {
    date_from?: string; date_to?: string
    profile_id?: string; account_id?: string; limit?: number
  }) => {
    const qs = new URLSearchParams()
    if (params.date_from) qs.set('date_from', params.date_from)
    if (params.date_to) qs.set('date_to', params.date_to)
    if (params.profile_id) qs.set('profile_id', params.profile_id)
    if (params.account_id) qs.set('account_id', params.account_id)
    if (params.limit != null) qs.set('limit', String(params.limit))
    return request<import('./types').AdGroupWithMetrics[]>(`/performance/ad-groups?${qs}`)
  },

  /** Keywords/targets across a profile/account, highest spend first. */
  listTargetsWithMetrics: (params: {
    date_from?: string; date_to?: string
    profile_id?: string; account_id?: string
    target_kind?: string; limit?: number
  }) => {
    const qs = new URLSearchParams()
    if (params.date_from) qs.set('date_from', params.date_from)
    if (params.date_to) qs.set('date_to', params.date_to)
    if (params.profile_id) qs.set('profile_id', params.profile_id)
    if (params.account_id) qs.set('account_id', params.account_id)
    if (params.target_kind) qs.set('target_kind', params.target_kind)
    if (params.limit != null) qs.set('limit', String(params.limit))
    return request<import('./types').TargetsWithMetricsPage>(`/performance/targets?${qs}`)
  },

  // ── Rule templates ──────────────────────────────────────────────────────

  listRuleTemplates: (ruleType?: string) =>
    request<import('./types').RuleTemplate[]>(
      '/rule-templates' + (ruleType ? `?rule_type=${ruleType}` : ''),
    ),

  createRuleTemplate: (body: {
    name: string; description?: string | null
    rule_type: string; configuration_json: Record<string, unknown>
  }) => request<import('./types').RuleTemplate>('/rule-templates', {
    method: 'POST', body: JSON.stringify(body),
  }),

  deleteRuleTemplate: (id: string) =>
    request<void>(`/rule-templates/${id}`, { method: 'DELETE' }),

  listSyncJobs: (params?: { limit?: number; account_id?: string }) => {
    const qs = new URLSearchParams()
    if (params?.limit != null) qs.set('limit', String(params.limit))
    if (params?.account_id) qs.set('account_id', params.account_id)
    return request<import('./types').SyncJobsPage>(`/sync-jobs?${qs}`)
  },

  // ── Users (admin only) ──────────────────────────────────────────────────

  listUsers: () => request<import('./types').ManagedUser[]>('/auth/users'),

  createUser: (body: { email: string; name: string; password: string; role: string }) =>
    request<import('./types').ManagedUser>('/auth/users', {
      method: 'POST', body: JSON.stringify(body),
    }),

  updateUser: (id: string, body: { name?: string; role?: string; is_active?: boolean }) =>
    request<import('./types').ManagedUser>(`/auth/users/${id}`, {
      method: 'PATCH', body: JSON.stringify(body),
    }),

  resetUserPassword: (id: string, password: string) =>
    request<void>(`/auth/users/${id}/password`, {
      method: 'POST', body: JSON.stringify({ password }),
    }),

  syncPerformance: (accountId: string, days?: number) => {
    const qs = new URLSearchParams()
    qs.set('account_id', accountId)
    if (days != null) qs.set('days', String(days))
    return request<import('./types').PerfSyncResponse>(`/performance/sync?${qs}`, { method: 'POST' })
  },

  // ── Dev / bootstrap ─────────────────────────────────────────
  bootstrapDemoData: () =>
    request<unknown>('/dev/bootstrap-demo-data', { method: 'POST' }),

  // ── Account management ───────────────────────────────────────
  deleteAccount: (id: string) =>
    request<void>(`/accounts/${id}`, { method: 'DELETE' }),
}

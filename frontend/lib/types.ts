// TypeScript types matching Sprint 1A–3.5 backend Pydantic schemas

export interface User {
  id: string
  email: string
  name: string
  role: string
}

// Sprint 3.5 — connection mode
export type ConnectionMode = 'mock' | 'real'

export interface CredentialStatus {
  connected: boolean
  token_expires_at: string | null
  mode: ConnectionMode
  last_synced_at: string | null
}

export interface Account {
  id: string
  name: string
  created_at: string
  profile_count: number
  credential_status: CredentialStatus
}

export interface AccountDetail {
  id: string
  name: string
  created_at: string
  updated_at: string
  credential_status: CredentialStatus
}

export interface Profile {
  id: string
  seller_account_id: string
  amazon_profile_id: number
  marketplace_code: string
  country_code: string | null
  currency_code: string | null
  timezone: string | null
  status: string
  last_synced_at: string | null
}

export interface Campaign {
  id: string
  profile_id: string
  amazon_campaign_id: number
  ad_product: string
  name: string
  status: string
  targeting_type: string | null
  daily_budget: number | null
  start_date: string | null
  end_date: string | null
  bidding_strategy: string | null
  last_synced_at: string | null
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export interface AdGroup {
  id: string
  campaign_id: string
  amazon_ad_group_id: number
  name: string
  default_bid: number | null
  status: string
  last_synced_at: string | null
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export interface Target {
  id: string
  ad_group_id: string
  amazon_target_id: number
  target_kind: string
  match_type: string | null
  expression_text: string | null
  bid: number | null
  status: string
  last_synced_at: string | null
  deleted_at: string | null
  created_at: string
  updated_at: string
}

export interface SyncResult {
  upserted: number
  soft_deleted: number
  partial?: boolean
  warnings?: string[]
  pages_fetched?: number
  rows_fetched?: number
}

export interface SyncAllResponse {
  message: string
  seller_account_id: string
  campaigns: SyncResult
  ad_groups: SyncResult
  targets: SyncResult
}

/** GET /accounts/{id}/sync-status — DB counts loaded on page mount */
export interface SyncStatusEntry {
  count: number
  last_synced_at: string | null
}

export interface SyncJob {
  running: boolean
  started_at: string | null
  completed_at: string | null
  error: string | null
  result: Record<string, unknown> | null
  // Added when job state moved from an in-memory dict to the sync_jobs table.
  // `running` is retained with its original meaning so existing polling works.
  job_id: string | null
  // queued | running | success | failed | partial
  // 'partial' means the sync ran but Amazon returned an incomplete view.
  status: string | null
  records_synced: number
}

export interface SyncStatus {
  campaigns: SyncStatusEntry
  ad_groups: SyncStatusEntry
  targets: SyncStatusEntry
  sync_job?: SyncJob
}

export interface OAuthStartResponse {
  auth_url: string
  seller_account_id: string
  note: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

// ── Sprint 2: Search Terms ─────────────────────────────────────────────────

export interface SearchTermRow {
  search_term: string
  campaign_id: string | null
  campaign_name: string | null
  ad_group_id: string | null
  ad_group_name: string | null
  impressions: number
  clicks: number
  cost: string
  sales: string
  orders: number
  units: number
  ctr: string
  cpc: string
  acos: string | null
  roas: string | null
  conversion_rate: string
}

export interface SearchTermSyncResponse {
  message: string
  account_id: string
  terms_synced: number
  suggestions_generated: number
}

// ── Sprint 2: Suggestions ──────────────────────────────────────────────────

export interface MetricsSnapshot {
  impressions: number
  clicks: number
  cost: string
  sales: string
  orders: number
  acos: string | null
  roas: string | null
  ctr: string
  conversion_rate: string
}

export type SuggestionKind   = 'negative' | 'harvest' | 'bid'
export type SuggestionStatus = 'pending'  | 'approved' | 'rejected'
export type SuggestionType   =
  | 'negative_exact'
  | 'negative_phrase'
  | 'keyword_exact'
  | 'keyword_phrase'
  | 'keyword_broad'
  | 'bid_decrease'
  | 'bid_increase'

export interface Suggestion {
  id: string
  profile_id: string
  campaign_id: string | null
  ad_group_id: string | null
  search_term: string
  suggestion_type: string
  kind: SuggestionKind
  reason: string
  metrics_snapshot: MetricsSnapshot
  status: SuggestionStatus
  resolved_by: string | null
  resolved_at: string | null
  created_at: string
  updated_at: string
  confidence_score: number
  campaign_count: number
  ad_group_count: number
  total_spend: string
  total_sales: string
  total_orders: number
  source_type: string
  source_rule_id: string | null
  source_rule_name: string | null
}

export interface GenerateResponse {
  profile_id: string
  suggestions_generated: number
}

export interface BulkResolveResponse {
  resolved: number
  skipped: number
}

// ── Sprint 3: Rules Engine ─────────────────────────────────────────────────

export type RuleType   = 'negative' | 'harvest' | 'bid'
export type RuleStatus = 'enabled'  | 'disabled'
export type ExecStatus = 'running'  | 'completed' | 'failed'

export interface RuleCondition {
  field:    string
  operator: string
  value:    number
}

export interface BidAction {
  type:    'increase_bid' | 'decrease_bid'
  percent: number
}

export interface RuleConfiguration {
  conditions:      RuleCondition[]
  suggestion_type: string
  lookback_days:   number
  logic:           'AND' | 'OR'
  action?:         BidAction
}

export interface Rule {
  id:                 string
  profile_id:         string
  name:               string
  description:        string | null
  rule_type:          RuleType
  status:             RuleStatus
  configuration_json: RuleConfiguration
  created_by:         string | null
  created_at:         string
  updated_at:         string
  deleted_at:         string | null
}

export interface RuleExecution {
  id:                   string
  rule_id:              string
  profile_id:           string
  started_at:           string
  completed_at:         string | null
  execution_status:     ExecStatus
  rows_evaluated:       number
  suggestions_generated: number
  error_message:        string | null
  created_at:           string
}

export interface ExecuteRuleResponse {
  rule_id:               string
  rule_name:             string
  execution_id:          string
  rows_evaluated:        number
  suggestions_generated: number
  execution_status:      string
  duration_ms:           number
}

// ── Sprint 3.5: Connection diagnostics ────────────────────────────────────

export interface ConnectionTestStep {
  name: string     // credentials_stored | token_decrypt | token_refresh | profiles_api
  passed: boolean
  detail: string
}

export interface ConnectionTestResponse {
  account_id: string
  mode: ConnectionMode
  steps: ConnectionTestStep[]
  profile_count: number
  error: string | null
}

// ── Performance / metrics (Sprint 4B) ────────────────────────────────────

export interface PerfMetrics {
  impressions: number | null
  clicks: number | null
  spend: number | null
  sales: number | null
  orders: number | null
  ctr: number | null   // ratio 0-1
  cpc: number | null
  acos: number | null  // percentage
  roas: number | null
}

export interface CampaignWithMetrics extends Campaign, PerfMetrics {}

export interface AdGroupWithMetrics extends AdGroup, PerfMetrics {}

export interface TargetWithMetrics extends Target, PerfMetrics {}

export interface PerfSyncResult {
  campaign_rows: number
  ad_group_rows: number
  target_rows: number
  date_from: string | null
  date_to: string | null
  profiles_synced: number
}

export interface PerfSyncResponse {
  message: string
  result: PerfSyncResult
}

/** Campaign count per marketplace, used to explain empty screens. */
export interface ProfileCount {
  profile_id: string
  country_code: string | null
  campaigns: number
}

// ── Plan 3: Execution audit ────────────────────────────────────────────────

/** One row of change_log — something that really changed on Amazon. */
export interface ChangeLogEntry {
  id: string
  profile_id: string
  entity_type: string
  entity_id: string | null
  amazon_entity_id: number | null
  field_changed: string
  old_value: string | null
  new_value: string | null
  suggestion_id: string | null
  changed_by: string | null
  source: string            // suggestion_execution | manual_edit | rollback
  rolled_back_at: string | null
  changed_at: string | null
}

export interface ChangeLogResponse {
  count: number
  changes: ChangeLogEntry[]
}

/** One execution attempt, with the literal Amazon exchange. */
export interface SuggestionActionEntry {
  id: string
  action: string
  performed_by: string | null
  notes: string | null
  amazon_api_request: Record<string, unknown> | null
  amazon_api_response: Record<string, unknown> | null
  amazon_api_status_code: number | null
  created_at: string | null
}

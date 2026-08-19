'use client'
/**
 * Rules Engine page — Sprint 3
 *
 * Sections:
 *   1. Header + stats strip
 *   2. Rules table (list with inline actions)
 *   3. Create / Edit modal (condition builder)
 *   4. Execution result toast
 *   5. Execution history drawer (per rule)
 *
 * Rules NEVER auto-apply. They create Suggestions only.
 * Human approval of each suggestion is mandatory.
 */
import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { api, ApiError } from '@/lib/api'
import type {
  Rule, RuleExecution, ExecuteRuleResponse, RuleConfiguration, RuleCondition,
  Profile, RuleTemplate, AdGroup, Campaign } from '@/lib/types'

// ── Constants ─────────────────────────────────────────────────────────────────

const RULE_TYPE_LABELS: Record<string, string> = {
  negative: 'Negative',
  harvest:  'Harvest',
  bid:      'Bid Adjustment',
  budget:   'Budget',
  placement: 'Placement',
}

const RULE_TYPE_COLORS: Record<string, string> = {
  negative: 'bg-red-100 text-red-700',
  harvest:  'bg-green-100 text-green-700',
  bid:      'bg-purple-100 text-purple-700',
  budget:   'bg-blue-100 text-blue-700',
  placement: 'bg-teal-100 text-teal-700',
}

const EXEC_STATUS_COLORS: Record<string, string> = {
  completed: 'bg-green-100 text-green-700',
  running:   'bg-yellow-100 text-yellow-700',
  failed:    'bg-red-100 text-red-700',
}

const FIELD_OPTIONS = [
  { value: 'clicks',          label: 'Clicks',         unit: '' },
  { value: 'orders',          label: 'Orders',         unit: '' },
  { value: 'cost',            label: 'Spend',          unit: '$' },
  { value: 'sales',           label: 'Sales',          unit: '$' },
  { value: 'acos',            label: 'ACOS',           unit: '%' },
  { value: 'roas',            label: 'ROAS',           unit: 'x' },
  { value: 'ctr',             label: 'CTR',            unit: '%' },
  { value: 'conversion_rate', label: 'CVR',            unit: '%' },
  { value: 'impressions',     label: 'Impressions',    unit: '' },
]

const OP_OPTIONS = [
  { value: 'gt',  label: '>'  },
  { value: 'gte', label: '>=' },
  { value: 'lt',  label: '<'  },
  { value: 'lte', label: '<=' },
  { value: 'eq',  label: '='  },
  { value: 'neq', label: '≠'  },
]

// Suggestion type options per rule type
const SUGGESTION_TYPES: Record<string, { value: string; label: string }[]> = {
  negative: [
    { value: 'negative_exact',  label: 'Negative Exact' },
    { value: 'negative_phrase', label: 'Negative Phrase' },
  ],
  harvest: [
    { value: 'keyword_exact',  label: 'Keyword Exact' },
    { value: 'keyword_phrase', label: 'Keyword Phrase' },
    { value: 'keyword_broad',  label: 'Keyword Broad' },
  ],
  bid: [
    { value: 'bid_decrease', label: 'Decrease Bid' },
    { value: 'bid_increase', label: 'Increase Bid' },
  ],
  budget: [
    { value: 'budget_decrease', label: 'Decrease Daily Budget' },
    { value: 'budget_increase', label: 'Increase Daily Budget' },
  ],
  placement: [
    { value: 'placement_increase', label: 'Raise Placement Bid Adjustment' },
    { value: 'placement_decrease', label: 'Lower Placement Bid Adjustment' },
  ],
}

const LOOKBACK_OPTIONS = [
  { value: 7,  label: '7 days' },
  { value: 14, label: '14 days' },
  { value: 30, label: '30 days' },
  { value: 60, label: '60 days' },
  { value: 90, label: '90 days' },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(s: string) {
  return new Date(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function fmtDateTime(s: string) {
  return new Date(s).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function fmtDuration(started: string, completed: string | null) {
  if (!completed) return '—'
  const ms = new Date(completed).getTime() - new Date(started).getTime()
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

function defaultConfig(ruleType: string): RuleConfiguration {
  const suggTypes = SUGGESTION_TYPES[ruleType] ?? []
  return {
    conditions:      [{ field: 'clicks', operator: 'gt', value: 20 }],
    suggestion_type: suggTypes[0]?.value ?? '',
    lookback_days:   30,
    logic:           'AND',
    action:
      ruleType === 'bid'    ? { type: 'decrease_bid', percent: 10 }
      : ruleType === 'budget' ? { type: 'decrease_budget', percent: 20 }
      // Placement defaults to RAISING, unlike bid and budget. A placement
      // adjustment starts at 0% for every campaign, so the only move available
      // on a fresh account is upward.
      : ruleType === 'placement' ? { type: 'increase_placement', percent: 25 }
      : undefined,
  }
}

// ── Execution History Drawer ──────────────────────────────────────────────────

function ExecHistoryDrawer({
  rule,
  executions,
  onClose,
}: {
  rule: Rule
  executions: RuleExecution[]
  onClose: () => void
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-white shadow-xl flex flex-col overflow-y-auto">
        {/* Header */}
        <div className="flex items-start justify-between px-5 py-4 border-b border-gray-200 sticky top-0 bg-white z-10">
          <div>
            <p className="text-xs text-gray-400 mb-1">Execution History</p>
            <h2 className="text-base font-semibold text-gray-900 truncate max-w-xs">{rule.name}</h2>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none mt-0.5">×</button>
        </div>

        {/* Executions list */}
        <div className="flex-1 divide-y divide-gray-100">
          {executions.length === 0 ? (
            <div className="px-5 py-10 text-center text-sm text-gray-400">
              No executions yet. Click "Run" to execute this rule.
            </div>
          ) : executions.map(ex => (
            <div key={ex.id} className="px-5 py-4">
              <div className="flex items-center justify-between mb-2">
                <span className={`text-xs px-2 py-0.5 rounded font-medium ${EXEC_STATUS_COLORS[ex.execution_status] ?? 'bg-gray-100 text-gray-600'}`}>
                  {ex.execution_status}
                </span>
                <span className="text-xs text-gray-400">{fmtDateTime(ex.started_at)}</span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-sm">
                <div className="bg-gray-50 rounded p-2.5 text-center">
                  <p className="text-xs text-gray-400">Rows Evaluated</p>
                  <p className="text-base font-semibold text-gray-800 mt-0.5">{ex.rows_evaluated}</p>
                </div>
                <div className="bg-green-50 rounded p-2.5 text-center">
                  <p className="text-xs text-gray-400">Suggestions Created</p>
                  <p className="text-base font-semibold text-green-700 mt-0.5">{ex.suggestions_generated}</p>
                </div>
                <div className="bg-gray-50 rounded p-2.5 text-center">
                  <p className="text-xs text-gray-400">Duration</p>
                  <p className="text-base font-semibold text-gray-800 mt-0.5">
                    {fmtDuration(ex.started_at, ex.completed_at)}
                  </p>
                </div>
              </div>
              {ex.error_message && (
                <div className="mt-2 text-xs text-red-600 bg-red-50 rounded p-2">
                  {ex.error_message}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Condition Row ─────────────────────────────────────────────────────────────

function ConditionRow({
  cond,
  idx,
  onChange,
  onRemove,
  canRemove,
}: {
  cond: RuleCondition
  idx: number
  onChange: (idx: number, updated: RuleCondition) => void
  onRemove: (idx: number) => void
  canRemove: boolean
}) {
  const fieldMeta = FIELD_OPTIONS.find(f => f.value === cond.field)

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {/* Field */}
      <select
        value={cond.field}
        onChange={e => onChange(idx, { ...cond, field: e.target.value })}
        className="input text-sm py-1.5 pr-7 flex-shrink-0 w-36"
      >
        {FIELD_OPTIONS.map(f => (
          <option key={f.value} value={f.value}>{f.label}{f.unit ? ` (${f.unit})` : ''}</option>
        ))}
      </select>

      {/* Operator */}
      <select
        value={cond.operator}
        onChange={e => onChange(idx, { ...cond, operator: e.target.value })}
        className="input text-sm py-1.5 pr-7 flex-shrink-0 w-16"
      >
        {OP_OPTIONS.map(op => (
          <option key={op.value} value={op.value}>{op.label}</option>
        ))}
      </select>

      {/* Value */}
      <div className="relative flex-shrink-0">
        {fieldMeta?.unit === '$' && (
          <span className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
        )}
        <input
          type="number"
          value={cond.value}
          step="any"
          min="0"
          onChange={e => onChange(idx, { ...cond, value: parseFloat(e.target.value) || 0 })}
          className={`input text-sm py-1.5 w-24 ${fieldMeta?.unit === '$' ? 'pl-6' : ''}`}
        />
        {fieldMeta?.unit && fieldMeta.unit !== '$' && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 text-xs">
            {fieldMeta.unit}
          </span>
        )}
      </div>

      {/* Remove */}
      {canRemove && (
        <button
          type="button"
          onClick={() => onRemove(idx)}
          className="text-gray-400 hover:text-red-500 transition-colors text-lg leading-none"
          title="Remove condition"
        >
          ×
        </button>
      )}
    </div>
  )
}

// ── Rule Form Modal ───────────────────────────────────────────────────────────

type FormMode = 'create' | 'edit'

/**
 * Which campaigns and ad groups a rule is allowed to act on.
 *
 * Empty means the whole marketplace — the behaviour every rule had before this
 * was reachable, so existing rules are unaffected. rule_campaign_scope has
 * existed since P4-4 and the engine always filtered on it, but no endpoint
 * accepted the ids, so nothing could ever be scoped.
 *
 * Ad groups are the point of the request: one campaign's ad groups target
 * completely different keywords and ASINs, so "negative anything over 60% ACoS
 * in this campaign" is too blunt when one ad group harvests broad and another
 * runs exact.
 */
function ScopePicker({
  campaigns, adGroups, campaignIds, adGroupIds, onChange, allowAdGroups,
}: {
  campaigns: Campaign[]
  adGroups: AdGroup[]
  campaignIds: string[]
  adGroupIds: string[]
  onChange: (next: { campaign_ids: string[]; ad_group_ids: string[] }) => void
  allowAdGroups: boolean
}) {
  const [tab, setTab] = useState<'campaigns' | 'adgroups'>('campaigns')
  const [q, setQ] = useState('')

  const campSet = new Set(campaignIds)
  const agSet = new Set(adGroupIds)

  // Only ad groups inside the chosen campaigns. Offering all of them would let
  // an operator pick one the API then rejects, and with no campaign chosen the
  // list would be the entire marketplace.
  const selectableAdGroups = useMemo(() => {
    const pool = campaignIds.length
      ? adGroups.filter(g => campSet.has(g.campaign_id))
      : adGroups
    const needle = q.trim().toLowerCase()
    return pool
      .filter(g => !needle || g.name.toLowerCase().includes(needle))
      .slice(0, 300)
  }, [adGroups, campaignIds, q]) // eslint-disable-line react-hooks/exhaustive-deps

  const visibleCampaigns = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return campaigns.filter(c => !needle || c.name.toLowerCase().includes(needle)).slice(0, 300)
  }, [campaigns, q])

  function toggleCampaign(id: string) {
    const next = new Set(campSet)
    if (next.has(id)) {
      next.delete(id)
      // Dropping a campaign must drop its ad groups too, or the rule would
      // carry an ad-group scope the API refuses on save.
      const orphaned = new Set(adGroups.filter(g => g.campaign_id === id).map(g => g.id))
      onChange({
        campaign_ids: [...next],
        ad_group_ids: adGroupIds.filter(g => !orphaned.has(g)),
      })
      return
    }
    next.add(id)
    onChange({ campaign_ids: [...next], ad_group_ids: adGroupIds })
  }

  function toggleAdGroup(id: string) {
    const next = new Set(agSet)
    next.has(id) ? next.delete(id) : next.add(id)
    onChange({ campaign_ids: campaignIds, ad_group_ids: [...next] })
  }

  const scopeSummary = campaignIds.length === 0 && adGroupIds.length === 0
    ? 'Every campaign in this marketplace'
    : [
        campaignIds.length ? `${campaignIds.length} campaign${campaignIds.length === 1 ? '' : 's'}` : null,
        adGroupIds.length ? `${adGroupIds.length} ad group${adGroupIds.length === 1 ? '' : 's'}` : null,
      ].filter(Boolean).join(' · ')

  return (
    <div className="rounded-lg border border-gray-200 p-3">
      <div className="flex items-center justify-between gap-2 flex-wrap mb-2">
        <div>
          <p className="text-sm font-medium text-gray-800">Apply this rule to</p>
          <p className="text-xs text-gray-500">{scopeSummary}</p>
        </div>
        {(campaignIds.length > 0 || adGroupIds.length > 0) && (
          <button type="button" className="text-xs text-blue-600 hover:underline"
                  onClick={() => onChange({ campaign_ids: [], ad_group_ids: [] })}>
            Clear — run on everything
          </button>
        )}
      </div>

      <div className="flex items-center gap-1 mb-2 text-xs">
        <button type="button" onClick={() => setTab('campaigns')}
                className={`px-2 py-1 rounded ${tab === 'campaigns'
                  ? 'bg-blue-600 text-white' : 'bg-white border border-gray-300'}`}>
          Campaigns{campaignIds.length ? ` (${campaignIds.length})` : ''}
        </button>
        <button type="button" onClick={() => setTab('adgroups')} disabled={!allowAdGroups}
                title={allowAdGroups ? undefined
                  : 'Budget and placement live on the campaign in Amazon, not the ad group'}
                className={`px-2 py-1 rounded disabled:opacity-40 ${tab === 'adgroups'
                  ? 'bg-blue-600 text-white' : 'bg-white border border-gray-300'}`}>
          Ad Groups{adGroupIds.length ? ` (${adGroupIds.length})` : ''}
        </button>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="Search…"
               className="input text-xs py-1 px-2 ml-auto w-40" />
      </div>

      {!allowAdGroups && (
        <p className="text-xs text-gray-500 mb-2">
          Amazon holds the budget and the placement adjustments on the campaign,
          so this rule type can only be scoped by campaign.
        </p>
      )}

      <div className="max-h-52 overflow-y-auto border border-gray-100 rounded">
        {tab === 'campaigns' ? (
          visibleCampaigns.length === 0 ? (
            // "No campaigns match" was shown before a marketplace was chosen,
            // which blames the search box for a different problem.
            <p className="text-xs text-gray-400 p-3">
              {campaigns.length === 0
                ? 'Choose a marketplace for this rule first — campaigns belong to one marketplace.'
                : 'No campaigns match that search.'}
            </p>
          ) : visibleCampaigns.map(c => (
            <label key={c.id}
                   className="flex items-center gap-2 px-2 py-1.5 text-xs hover:bg-gray-50 cursor-pointer">
              <input type="checkbox" checked={campSet.has(c.id)}
                     onChange={() => toggleCampaign(c.id)} />
              <span className="truncate" title={c.name}>{c.name}</span>
              <span className="ml-auto text-gray-400 shrink-0">{c.status}</span>
            </label>
          ))
        ) : selectableAdGroups.length === 0 ? (
          <p className="text-xs text-gray-400 p-3">
            {campaignIds.length === 0
              ? 'Pick a campaign first, or search to narrow this list.'
              : 'No ad groups in the selected campaigns match.'}
          </p>
        ) : selectableAdGroups.map(g => (
          <label key={g.id}
                 className="flex items-center gap-2 px-2 py-1.5 text-xs hover:bg-gray-50 cursor-pointer">
            <input type="checkbox" checked={agSet.has(g.id)}
                   onChange={() => toggleAdGroup(g.id)} />
            <span className="truncate" title={g.name}>{g.name}</span>
          </label>
        ))}
      </div>

      {adGroupIds.length > 0 && campaignIds.length === 0 && (
        <p className="text-xs text-amber-700 mt-2">
          Ad groups are selected with no campaign chosen. Add their campaigns too —
          the API refuses an ad group outside the campaign scope, because it would
          match nothing and the rule would look broken rather than misconfigured.
        </p>
      )}
    </div>
  )
}

function RuleModal({
  mode,
  initial,
  profileId,
  profiles,
  seed,
  onSave,
  onClose,
}: {
  mode: FormMode
  /** '' when the header is on "All Profiles" — the user must then pick one. */
  profileId: string
  initial?: Rule
  profiles: Profile[]
  /** Pre-fills a brand-new rule from a template. Ignored when editing. */
  seed?: RuleTemplate
  onSave: (rule: Rule) => void
  onClose: () => void
}) {
  // A rule lives in exactly one marketplace. Never guess it: creating a US
  // rule against the CA profile would run it on the wrong account's data.
  const [pickedProfile, setPickedProfile] = useState(
    initial?.profile_id ?? profileId ?? ''
  )
  const mustPickProfile = mode === 'create' && !profileId
  const [name,        setName]        = useState(initial?.name ?? seed?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? seed?.description ?? '')
  const [ruleType,    setRuleType]    = useState<string>(initial?.rule_type ?? seed?.rule_type ?? 'negative')
  // Scope. Empty = the whole marketplace, matching how rules behaved before.
  const [campaignIds, setCampaignIds] = useState<string[]>(initial?.campaign_ids ?? [])
  const [adGroupIds,  setAdGroupIds]  = useState<string[]>(initial?.ad_group_ids ?? [])
  const [scopeCampaigns, setScopeCampaigns] = useState<Campaign[]>([])
  const [scopeAdGroups,  setScopeAdGroups]  = useState<AdGroup[]>([])
  // Budget and placement act on whole campaigns in Amazon, so an ad-group scope
  // there would be stored and then ignored; the API rejects it.
  const allowAdGroups = ruleType !== 'budget' && ruleType !== 'placement'
  const [status,      setStatus]      = useState<string>(initial?.status ?? 'enabled')
  const [config,      setConfig]      = useState<RuleConfiguration>(
    initial?.configuration_json
      ?? seed?.configuration_json
      ?? defaultConfig(initial?.rule_type ?? 'negative')
  )
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState<string | null>(null)

  // When rule type changes, reset config with appropriate defaults
  function handleTypeChange(newType: string) {
    setRuleType(newType)
    setConfig(defaultConfig(newType))
  }

  function updateCondition(idx: number, updated: RuleCondition) {
    setConfig(c => ({
      ...c,
      conditions: c.conditions.map((cond, i) => i === idx ? updated : cond),
    }))
  }

  function addCondition() {
    setConfig(c => ({
      ...c,
      conditions: [...c.conditions, { field: 'clicks', operator: 'gt', value: 10 }],
    }))
  }

  function removeCondition(idx: number) {
    setConfig(c => ({
      ...c,
      conditions: c.conditions.filter((_, i) => i !== idx),
    }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) { setError('Name is required'); return }
    if (!pickedProfile) { setError('Choose a marketplace for this rule'); return }
    if (config.conditions.length === 0) { setError('Add at least one condition'); return }
    if (!config.suggestion_type) { setError('Select a suggestion type'); return }

    setSaving(true)
    setError(null)
    try {
      let saved: Rule
      const payload = {
        profile_id:         pickedProfile,
        name:               name.trim(),
        description:        description.trim() || null,
        rule_type:          ruleType,
        status,
        configuration_json: config as unknown as Record<string, unknown>,
        campaign_ids:       campaignIds,
        ad_group_ids:       allowAdGroups ? adGroupIds : [],
      }
      if (mode === 'create') {
        saved = await api.createRule(payload)
      } else {
        saved = await api.updateRule(initial!.id, {
          name:               payload.name,
          description:        payload.description,
          rule_type:          payload.rule_type,
          status:             payload.status,
          configuration_json: payload.configuration_json,
          campaign_ids:       payload.campaign_ids,
          ad_group_ids:       payload.ad_group_ids,
        })
      }
      onSave(saved)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    api.listCampaigns().then(all => setScopeCampaigns(
      all.filter(c => c.profile_id === pickedProfile))).catch(() => {})
    api.listAdGroups().then(setScopeAdGroups).catch(() => {})
  }, [pickedProfile])

  // Switching to a campaign-level type drops any ad-group scope, so the form
  // cannot submit a combination the API refuses.
  useEffect(() => {
    if (!allowAdGroups && adGroupIds.length > 0) setAdGroupIds([])
  }, [allowAdGroups, adGroupIds.length])

  const suggOptions = SUGGESTION_TYPES[ruleType] ?? []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-full max-w-2xl bg-white rounded-xl shadow-2xl flex flex-col max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">
            {mode === 'create' ? 'Create Rule' : 'Edit Rule'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto">
          <div className="px-6 py-5 space-y-5">
            {/* Marketplace — only when the header can't tell us which one */}
            {mustPickProfile && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Marketplace <span className="text-red-500">*</span>
                </label>
                <select
                  value={pickedProfile}
                  onChange={e => setPickedProfile(e.target.value)}
                  className="input w-full"
                  required
                >
                  <option value="">Choose a marketplace…</option>
                  {profiles.map(p => (
                    <option key={p.id} value={p.id}>
                      {p.country_code ?? p.marketplace_code}
                      {p.currency_code ? ` – ${p.currency_code}` : ''}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-400 mt-1">
                  A rule only sees data from the marketplace it belongs to.
                </p>
              </div>
            )}

            {/* Name */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Name <span className="text-red-500">*</span></label>
              <input
                type="text"
                value={name}
                onChange={e => setName(e.target.value)}
                placeholder="e.g. Negative: High Spend No Sales"
                className="input w-full"
                required
              />
            </div>

            {/* Description */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
              <textarea
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder="Optional description of what this rule does…"
                rows={2}
                className="input w-full resize-none"
              />
            </div>

            {/* Rule Type + Status row */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Rule Type</label>
                {/* Driven by RULE_TYPE_LABELS rather than hardcoded, so adding a
                    rule type cannot leave the picker behind again. Budget rules
                    shipped unreachable this way: the engine and the suggestion
                    types were done, but this list still had three entries. */}
                <select value={ruleType} onChange={e => handleTypeChange(e.target.value)} className="input w-full">
                  {Object.keys(SUGGESTION_TYPES).map(t => (
                    <option key={t} value={t}>{RULE_TYPE_LABELS[t] ?? t}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
                <select value={status} onChange={e => setStatus(e.target.value)} className="input w-full">
                  <option value="enabled">Enabled</option>
                  <option value="disabled">Disabled</option>
                </select>
              </div>
            </div>

            {/* Scope — which campaigns / ad groups this rule may act on */}
            <ScopePicker
              campaigns={scopeCampaigns}
              adGroups={scopeAdGroups}
              campaignIds={campaignIds}
              adGroupIds={adGroupIds}
              allowAdGroups={allowAdGroups}
              onChange={next => {
                setCampaignIds(next.campaign_ids)
                setAdGroupIds(next.ad_group_ids)
              }}
            />

            {/* Conditions */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="block text-sm font-medium text-gray-700">
                  Conditions <span className="text-red-500">*</span>
                </label>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-500">Logic:</span>
                  <div className="flex rounded border border-gray-200 overflow-hidden text-xs">
                    {(['AND', 'OR'] as const).map(l => (
                      <button
                        key={l} type="button"
                        onClick={() => setConfig(c => ({ ...c, logic: l }))}
                        className={`px-2.5 py-1 transition-colors ${
                          config.logic === l ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
                        }`}
                      >
                        {l}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="space-y-2.5 p-3 bg-gray-50 rounded-lg border border-gray-200">
                {config.conditions.map((cond, idx) => (
                  <ConditionRow
                    key={idx}
                    cond={cond}
                    idx={idx}
                    onChange={updateCondition}
                    onRemove={removeCondition}
                    canRemove={config.conditions.length > 1}
                  />
                ))}
                <button
                  type="button"
                  onClick={addCondition}
                  className="text-sm text-blue-600 hover:underline"
                >
                  + Add Condition
                </button>
                <p className="text-xs text-gray-400">
                  ACOS/CTR/CVR values are percentages (enter 30 for 30%)
                </p>
              </div>
            </div>

            {/* Suggestion type + Lookback row */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Creates Suggestion Type</label>
                <select
                  value={config.suggestion_type}
                  onChange={e => setConfig(c => ({ ...c, suggestion_type: e.target.value }))}
                  className="input w-full"
                >
                  {suggOptions.map(s => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Lookback Period</label>
                <select
                  value={config.lookback_days}
                  onChange={e => setConfig(c => ({ ...c, lookback_days: parseInt(e.target.value) }))}
                  className="input w-full"
                >
                  {LOOKBACK_OPTIONS.map(o => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Bid action — only for bid rules */}
            {ruleType === 'bid' && (
              <div className="p-3 bg-purple-50 rounded-lg border border-purple-200">
                <label className="block text-sm font-medium text-gray-700 mb-2">Bid Adjustment Action</label>
                <div className="flex items-center gap-3">
                  <select
                    value={config.action?.type ?? 'decrease_bid'}
                    onChange={e => setConfig(c => ({
                      ...c,
                      suggestion_type: e.target.value === 'decrease_bid' ? 'bid_decrease' : 'bid_increase',
                      action: { ...c.action, type: e.target.value as 'decrease_bid' | 'increase_bid', percent: c.action?.percent ?? 10 },
                    }))}
                    className="input text-sm py-1.5 flex-1"
                  >
                    <option value="decrease_bid">Decrease bid</option>
                    <option value="increase_bid">Increase bid</option>
                  </select>
                  <span className="text-sm text-gray-600">by</span>
                  <input
                    type="number"
                    min="1"
                    max="100"
                    value={config.action?.percent ?? 10}
                    onChange={e => setConfig(c => ({
                      ...c,
                      action: { ...c.action!, percent: parseFloat(e.target.value) || 10 },
                    }))}
                    className="input text-sm py-1.5 w-20"
                  />
                  <span className="text-sm text-gray-600">%</span>
                </div>
              </div>
            )}

            {/* Budget action — only for budget rules */}
            {ruleType === 'budget' && (
              <div className="p-3 bg-blue-50 rounded-lg border border-blue-200">
                <label className="block text-sm font-medium text-gray-700 mb-2">Daily Budget Action</label>
                <div className="flex items-center gap-3">
                  <select
                    value={config.action?.type ?? 'decrease_budget'}
                    onChange={e => setConfig(c => ({
                      ...c,
                      suggestion_type: e.target.value === 'decrease_budget' ? 'budget_decrease' : 'budget_increase',
                      action: { ...c.action, type: e.target.value as 'decrease_budget' | 'increase_budget', percent: c.action?.percent ?? 20 },
                    }))}
                    className="input text-sm py-1.5 flex-1"
                  >
                    <option value="decrease_budget">Decrease daily budget</option>
                    <option value="increase_budget">Increase daily budget</option>
                  </select>
                  <span className="text-sm text-gray-600">by</span>
                  <input
                    type="number"
                    min="1"
                    max="100"
                    value={config.action?.percent ?? 20}
                    onChange={e => setConfig(c => ({
                      ...c,
                      action: { ...c.action!, percent: parseFloat(e.target.value) || 20 },
                    }))}
                    className="input text-sm py-1.5 w-20"
                  />
                  <span className="text-sm text-gray-600">%</span>
                </div>
                <p className="text-xs text-gray-500 mt-2">
                  Budget rules read whole-campaign totals, not search terms, and skip
                  campaigns started in the last 3 days — Amazon needs about 72 hours
                  before a new campaign&apos;s numbers mean anything. Amazon&apos;s minimum
                  daily budget is $1.00; a cut that would go below it is skipped.
                </p>
              </div>
            )}

            {/* Placement action — only for placement rules */}
            {ruleType === 'placement' && (
              <div className="p-3 bg-teal-50 rounded-lg border border-teal-200">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Placement Bid Adjustment
                </label>
                <div className="flex items-center gap-3">
                  <select
                    value={config.action?.type ?? 'increase_placement'}
                    onChange={e => setConfig(c => ({
                      ...c,
                      suggestion_type: e.target.value === 'increase_placement'
                        ? 'placement_increase' : 'placement_decrease',
                      action: { ...c.action, type: e.target.value as 'increase_placement' | 'decrease_placement', percent: c.action?.percent ?? 25 },
                    }))}
                    className="input text-sm py-1.5 flex-1"
                  >
                    <option value="increase_placement">Raise adjustment</option>
                    <option value="decrease_placement">Lower adjustment</option>
                  </select>
                  <span className="text-sm text-gray-600">by</span>
                  <input
                    type="number"
                    min="1"
                    max="900"
                    value={config.action?.percent ?? 25}
                    onChange={e => setConfig(c => ({
                      ...c,
                      action: { ...c.action!, percent: parseFloat(e.target.value) || 25 },
                    }))}
                    className="input text-sm py-1.5 w-20"
                  />
                  <span className="text-sm text-gray-600">points</span>
                </div>
                <p className="text-xs text-gray-500 mt-2">
                  Amazon&apos;s placement setting is a percentage uplift on your keyword
                  bid, from 0% to 900%. This adds or subtracts percentage
                  <span className="font-medium"> points</span> — 0% raised by 25 becomes
                  25%. Placement rules read whole-placement totals per campaign,
                  so check the Placements screen first to see which spots are
                  worth paying more for.
                </p>
              </div>
            )}

            {/* Info note */}
            <div className="flex items-start gap-2 p-3 bg-blue-50 rounded-lg border border-blue-100 text-xs text-blue-700">
              <span className="text-base leading-none mt-0.5">ℹ️</span>
              <span>
                Rules create <strong>Suggestions only</strong>. Nothing is applied to Amazon automatically.
                Every suggestion requires manual approval in the Suggestion Inbox.
              </span>
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2 text-sm text-red-700">{error}</div>
            )}
          </div>

          {/* Footer */}
          <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-end gap-3 bg-gray-50">
            <button type="button" onClick={onClose} className="btn-secondary">Cancel</button>
            <button type="submit" disabled={saving} className="btn-primary disabled:opacity-50">
              {saving ? 'Saving…' : mode === 'create' ? 'Create Rule' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function RulesPage() {
  const router = useRouter()
  const { user, loading: authLoading } = useAuth()
  const {
    currentAccountId, currentProfileId, accountProfileIds, profiles,
    accountsLoading, profilesLoading,
  } = useAccountProfile()

  const [rules,      setRules]      = useState<Rule[]>([])
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState<string | null>(null)
  const [toast,      setToast]      = useState<string | null>(null)
  const [toastErr,   setToastErr]   = useState<string | null>(null)

  // Modal state
  const [modalMode,  setModalMode]  = useState<FormMode | null>(null)
  const [editRule,   setEditRule]   = useState<Rule | undefined>(undefined)
  const [showTemplates, setShowTemplates] = useState(false)
  const [seed,       setSeed]       = useState<RuleTemplate | undefined>(undefined)

  // Per-rule action state
  const [running,    setRunning]    = useState<Record<string, boolean>>({})
  const [runResult,  setRunResult]  = useState<Record<string, ExecuteRuleResponse>>({})

  // Execution history drawer
  const [histRule,   setHistRule]   = useState<Rule | null>(null)
  const [histExecs,  setHistExecs]  = useState<RuleExecution[]>([])
  const [histLoading, setHistLoading] = useState(false)

  // Auth guard
  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  // Rules belong to one marketplace. With "All Profiles" selected there is no
  // single profile to query, and the old code silently picked whichever profile
  // happened to be first — so two real US rules rendered as "No rules yet".
  // Load every profile in the account instead and label each row.
  const profileId = currentProfileId ?? ''
  const hasAnyProfile = accountProfileIds.size > 0
  const profileIdsKey = useMemo(
    () => Array.from(accountProfileIds).sort().join(','),
    [accountProfileIds],
  )

  const load = useCallback(async () => {
    if (!hasAnyProfile || accountsLoading || profilesLoading) return
    const targets = currentProfileId ? [currentProfileId] : Array.from(accountProfileIds)
    setLoading(true)
    setError(null)
    try {
      const batches = await Promise.all(targets.map(pid => api.listRules(pid)))
      setRules(batches.flat())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load rules')
    } finally {
      setLoading(false)
    }
    // accountProfileIds is a fresh Set each render; profileIdsKey is the stable value.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentProfileId, profileIdsKey, hasAnyProfile, accountsLoading, profilesLoading])

  useEffect(() => {
    if (user && !accountsLoading && !profilesLoading && hasAnyProfile) load()
  }, [user, accountsLoading, profilesLoading, hasAnyProfile, load])

  function showToast(msg: string, isErr = false) {
    if (isErr) { setToastErr(msg); setTimeout(() => setToastErr(null), 4000) }
    else        { setToast(msg);   setTimeout(() => setToast(null),    4000) }
  }

  // ── Rule actions ──────────────────────────────────────────────────────────

  async function handleRun(rule: Rule) {
    setRunning(r => ({ ...r, [rule.id]: true }))
    setRunResult(r => { const n = { ...r }; delete n[rule.id]; return n })
    try {
      const res = await api.executeRule(rule.id)
      setRunResult(r => ({ ...r, [rule.id]: res }))
      showToast(`"${rule.name}" → ${res.suggestions_generated} suggestion${res.suggestions_generated !== 1 ? 's' : ''} created (${res.rows_evaluated} rows evaluated)`)
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : 'Execution failed', true)
    } finally {
      setRunning(r => ({ ...r, [rule.id]: false }))
    }
  }

  async function handleClone(rule: Rule) {
    try {
      const cloned = await api.cloneRule(rule.id)
      setRules(prev => [cloned, ...prev])
      showToast(`Cloned "${rule.name}" → "${cloned.name}" (disabled)`)
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : 'Clone failed', true)
    }
  }

  async function handleToggleStatus(rule: Rule) {
    try {
      const updated = rule.status === 'enabled'
        ? await api.disableRule(rule.id)
        : await api.enableRule(rule.id)
      setRules(prev => prev.map(r => r.id === rule.id ? updated : r))
      showToast(`"${updated.name}" ${updated.status}`)
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : 'Status update failed', true)
    }
  }

  async function handleDelete(rule: Rule) {
    if (!confirm(`Delete "${rule.name}"? This cannot be undone.`)) return
    try {
      await api.deleteRule(rule.id)
      setRules(prev => prev.filter(r => r.id !== rule.id))
      showToast(`Deleted "${rule.name}"`)
    } catch (e) {
      showToast(e instanceof ApiError ? e.message : 'Delete failed', true)
    }
  }

  async function handleViewHistory(rule: Rule) {
    setHistRule(rule)
    setHistLoading(true)
    setHistExecs([])
    try {
      const execs = await api.getRuleExecutions(rule.id, 20)
      setHistExecs(execs)
    } catch {
      // silently show empty
    } finally {
      setHistLoading(false)
    }
  }

  function handleSaved(saved: Rule) {
    if (modalMode === 'create') {
      setRules(prev => [saved, ...prev])
      showToast(`Created "${saved.name}"`)
    } else {
      setRules(prev => prev.map(r => r.id === saved.id ? saved : r))
      showToast(`Updated "${saved.name}"`)
    }
    setModalMode(null)
    setEditRule(undefined)
  }

  // ── Stats ─────────────────────────────────────────────────────────────────
  const stats = useMemo(() => ({
    total:    rules.length,
    enabled:  rules.filter(r => r.status === 'enabled').length,
    disabled: rules.filter(r => r.status === 'disabled').length,
  }), [rules])

  const noContext  = !accountsLoading && !currentAccountId
  const noProfiles = !profilesLoading && currentAccountId && !hasAnyProfile

  /** 'US', 'CA' … for the Marketplace column. */
  const profileLabel = useCallback((pid: string) => {
    const p = profiles.find(x => x.id === pid)
    return p ? (p.country_code ?? p.marketplace_code) : '—'
  }, [profiles])

  // Only meaningful when the header is on "All Profiles"; otherwise every row
  // is the same marketplace and the column is noise.
  const showMarketplaceCol = !currentProfileId && profiles.length > 1

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Rules Engine</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Configurable rules that create Suggestions. Nothing is auto-applied to Amazon.
          </p>
        </div>
        {!noContext && !noProfiles && (
          <div className="flex gap-2">
            {/* Templates first: a new marketplace has no rules to clone, and a
                blank condition form gives no hint what a sane threshold is. */}
            <button
              onClick={() => setShowTemplates(true)}
              className="px-4 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              Start from template
            </button>
            <button
              onClick={() => { setSeed(undefined); setEditRule(undefined); setModalMode('create') }}
              className="btn-primary"
            >
              + New Rule
            </button>
          </div>
        )}
      </div>

      {/* Stats strip */}
      {!noContext && !noProfiles && rules.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: 'Total Rules',    value: stats.total,    color: 'border-gray-200 bg-white' },
            { label: 'Enabled',        value: stats.enabled,  color: 'border-green-200 bg-green-50' },
            { label: 'Disabled',       value: stats.disabled, color: 'border-gray-200 bg-gray-50' },
          ].map(({ label, value, color }) => (
            <div key={label} className={`rounded-xl border p-4 ${color}`}>
              <p className="text-xs text-gray-500">{label}</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Toasts */}
      {toast && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2 text-sm text-green-700">
          ✓ {toast}
        </div>
      )}
      {toastErr && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2 text-sm text-red-700">
          ✗ {toastErr}
        </div>
      )}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {noContext && (
        <div className="card text-center py-12 text-gray-500">Select an account to manage rules.</div>
      )}
      {noProfiles && (
        <div className="card text-center py-12 text-gray-500">
          No profiles synced. Go to Settings → Accounts and sync profiles first.
        </div>
      )}

      {/* Rules table */}
      {!noContext && !noProfiles && (
        <div className="card p-0 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50">
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Name</th>
                {showMarketplaceCol && (
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 w-24">Marketplace</th>
                )}
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 w-28">Type</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 w-20">Status</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 w-28">Creates</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 w-20">Lookback</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 w-28">Created</th>
                <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600 w-52">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr><td colSpan={showMarketplaceCol ? 8 : 7} className="px-4 py-12 text-center text-gray-400">Loading…</td></tr>
              ) : rules.length === 0 ? (
                <tr><td colSpan={showMarketplaceCol ? 8 : 7} className="px-4 py-16 text-center">
                  <div className="text-gray-400 mb-3 text-base">No rules yet</div>
                  <button
                    onClick={() => { setSeed(undefined); setModalMode('create') }}
                    className="btn-primary text-sm"
                  >
                    Create your first rule
                  </button>
                </td></tr>
              ) : rules.map(rule => {
                const isRunning = running[rule.id]
                const runRes    = runResult[rule.id]
                const config    = rule.configuration_json
                return (
                  <tr key={rule.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-900 truncate max-w-[200px]" title={rule.name}>
                        {rule.name}
                      </div>
                      {rule.description && (
                        <div className="text-xs text-gray-400 truncate max-w-[200px] mt-0.5" title={rule.description}>
                          {rule.description}
                        </div>
                      )}
                      {runRes && (
                        <div className="text-xs text-green-600 mt-1">
                          ✓ {runRes.suggestions_generated} suggestions created ({runRes.rows_evaluated} rows, {runRes.duration_ms}ms)
                        </div>
                      )}
                    </td>
                    {showMarketplaceCol && (
                      <td className="px-4 py-3">
                        <span className="text-xs font-medium text-gray-600 bg-gray-100 rounded px-2 py-0.5">
                          {profileLabel(rule.profile_id)}
                        </span>
                      </td>
                    )}
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${RULE_TYPE_COLORS[rule.rule_type] ?? 'bg-gray-100 text-gray-600'}`}>
                        {RULE_TYPE_LABELS[rule.rule_type] ?? rule.rule_type}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                        rule.status === 'enabled' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                      }`}>
                        {rule.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600">
                      {config.suggestion_type?.replace(/_/g, ' ') ?? '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-600">
                      {config.lookback_days ?? 30}d
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {fmtDate(rule.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1.5 flex-wrap">
                        {/* Run */}
                        <button
                          onClick={() => handleRun(rule)}
                          disabled={isRunning || rule.status !== 'enabled'}
                          title={rule.status !== 'enabled' ? 'Enable rule to run' : 'Run now'}
                          className="text-xs px-2.5 py-1 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors font-medium"
                        >
                          {isRunning ? '⏳' : '▶ Run'}
                        </button>
                        {/* History */}
                        <button
                          onClick={() => handleViewHistory(rule)}
                          className="text-xs px-2.5 py-1 bg-white border border-gray-300 text-gray-600 rounded hover:bg-gray-50 transition-colors"
                          title="Execution history"
                        >
                          📋
                        </button>
                        {/* Edit */}
                        <button
                          onClick={() => { setEditRule(rule); setModalMode('edit') }}
                          className="text-xs px-2.5 py-1 bg-white border border-gray-300 text-gray-600 rounded hover:bg-gray-50 transition-colors"
                        >
                          Edit
                        </button>
                        {/* Clone */}
                        <button
                          onClick={() => handleClone(rule)}
                          className="text-xs px-2.5 py-1 bg-white border border-gray-300 text-gray-600 rounded hover:bg-gray-50 transition-colors"
                          title="Clone (creates disabled copy)"
                        >
                          Clone
                        </button>
                        {/* Enable / Disable */}
                        <button
                          onClick={() => handleToggleStatus(rule)}
                          className={`text-xs px-2.5 py-1 rounded border transition-colors ${
                            rule.status === 'enabled'
                              ? 'bg-white border-gray-300 text-gray-600 hover:bg-gray-50'
                              : 'bg-white border-green-300 text-green-600 hover:bg-green-50'
                          }`}
                        >
                          {rule.status === 'enabled' ? 'Disable' : 'Enable'}
                        </button>
                        {/* Delete */}
                        <button
                          onClick={() => handleDelete(rule)}
                          className="text-xs px-2.5 py-1 bg-white border border-red-200 text-red-500 rounded hover:bg-red-50 transition-colors"
                          title="Delete rule"
                        >
                          ✕
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Create / Edit modal */}
      {modalMode && (
        <RuleModal
          mode={modalMode}
          initial={editRule}
          profileId={profileId}
          profiles={profiles}
          seed={seed}
          onSave={handleSaved}
          onClose={() => { setModalMode(null); setEditRule(undefined); setSeed(undefined) }}
        />
      )}

      {showTemplates && (
        <TemplatePickerModal
          onClose={() => setShowTemplates(false)}
          onPick={t => {
            setSeed(t)
            setEditRule(undefined)
            setShowTemplates(false)
            setModalMode('create')
          }}
        />
      )}

      {/* Execution history drawer */}
      {histRule && (
        <ExecHistoryDrawer
          rule={histRule}
          executions={histLoading ? [] : histExecs}
          onClose={() => { setHistRule(null); setHistExecs([]) }}
        />
      )}
    </div>
  )
}

// ── Template Picker ───────────────────────────────────────────────────────────

/**
 * Cloning covers "another one like that". This covers the harder case: a
 * marketplace with no rules at all, where the condition builder is a blank
 * form and nothing suggests what a reasonable ACoS threshold looks like.
 */
function TemplatePickerModal({
  onClose, onPick,
}: { onClose: () => void; onPick: (t: RuleTemplate) => void }) {
  const [templates, setTemplates] = useState<RuleTemplate[]>([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState<string | null>(null)

  useEffect(() => {
    api.listRuleTemplates()
      .then(setTemplates)
      .catch(e => setError(e instanceof ApiError ? e.message : 'Failed to load templates'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  function describe(t: RuleTemplate): string {
    const c = t.configuration_json
    const conds = (c.conditions ?? [])
      .map(x => `${x.field} ${OP_OPTIONS.find(o => o.value === x.operator)?.label ?? x.operator} ${x.value}`)
      .join(` ${c.logic ?? 'AND'} `)
    return `IF ${conds} → ${c.suggestion_type} · ${c.lookback_days}d lookback`
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col">
        <div className="flex items-start justify-between px-6 py-4 border-b border-gray-200">
          <div>
            <h2 className="font-semibold text-gray-900">Start from a template</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              You can change every threshold after picking one. Nothing runs until you save.
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-2">
          {loading ? (
            <p className="text-sm text-gray-400 py-8 text-center">Loading…</p>
          ) : error ? (
            <p className="text-sm text-red-600 py-8 text-center">{error}</p>
          ) : templates.length === 0 ? (
            <p className="text-sm text-gray-400 py-8 text-center">No templates available.</p>
          ) : templates.map(t => (
            <button
              key={t.id}
              onClick={() => onPick(t)}
              className="w-full text-left border border-gray-200 rounded-lg p-3 hover:border-blue-400 hover:bg-blue-50/40 transition-colors"
            >
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-xs px-2 py-0.5 rounded font-medium ${RULE_TYPE_COLORS[t.rule_type] ?? 'bg-gray-100 text-gray-600'}`}>
                  {RULE_TYPE_LABELS[t.rule_type] ?? t.rule_type}
                </span>
                <span className="font-medium text-gray-900 text-sm">{t.name}</span>
                {t.is_builtin && (
                  <span className="text-[10px] uppercase tracking-wide text-gray-400 ml-auto">built-in</span>
                )}
              </div>
              {t.description && <p className="text-xs text-gray-600 mb-1.5">{t.description}</p>}
              <p className="text-xs font-mono text-gray-500">{describe(t)}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

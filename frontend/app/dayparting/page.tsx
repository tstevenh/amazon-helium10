'use client'
/**
 * Dayparting — pause and re-enable campaigns by hour and weekday.
 *
 * Spec §13.7. The operator picks the hours; the app does not recommend them,
 * because Amazon exposes no hourly performance data for Sponsored Products.
 *
 * This is the only screen in the app that hands a piece of a live account to a
 * timer, so the UI is deliberately blunt about it: schedules are created
 * inactive, activation is a separate click with a confirmation naming the
 * consequence, and the run history is one click away from every schedule.
 */
import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { Eye, History, Pencil, Play, Square, Trash2, X } from 'lucide-react'
import { api, ApiError } from '@/lib/api'
import type { Campaign, DaypartingEntryInput, DaypartingSchedule, DaypartingRun } from '@/lib/types'
import { Notice } from '@/components/ui/Notice'
import { Button } from '@/components/ui/Button'
import { MenuItem, MenuSeparator, RowMenu } from '@/components/ui/Menu'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/ui/LoadingState'
import { ErrorState } from '@/components/ui/ErrorState'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const HOURS = Array.from({ length: 24 }, (_, h) => h)

/** 0 → "12am", 13 → "1pm". Hour labels, not times of day. */
function hourLabel(h: number): string {
  if (h === 0) return '12am'
  if (h === 12) return '12pm'
  return h < 12 ? `${h}am` : `${h - 12}pm`
}

const OUTCOME_STYLE: Record<string, string> = {
  applied: 'bg-info-tint text-accent',
  already_correct: 'bg-surface-sunken text-ink-muted',
  skipped_writes_disabled: 'bg-warn-tint text-warn',
  skipped_no_timezone: 'bg-warn-tint text-warn',
  failed: 'bg-danger-tint text-danger',
}

function outcomeLabel(o: string): string {
  return {
    applied: 'changed',
    already_correct: 'no change needed',
    skipped_writes_disabled: 'blocked — writes off',
    skipped_no_timezone: 'skipped — no timezone',
    failed: 'failed',
  }[o] ?? o
}

export default function DaypartingPage() {
  const { user, loading: authLoading } = useAuth()
  const { currentProfileId, profiles, accountProfileIds, currentAccountId,
          accountsLoading, profilesLoading } = useAccountProfile()
  const router = useRouter()

  const [schedules, setSchedules] = useState<DaypartingSchedule[]>([])
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState<string | null>(null)
  const [toast, setToast]         = useState<string | null>(null)
  const [toastErr, setToastErr]   = useState<string | null>(null)
  const [editing, setEditing]     = useState<DaypartingSchedule | 'new' | null>(null)
  const [runsFor, setRunsFor]     = useState<DaypartingSchedule | null>(null)

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const load = useCallback(async () => {
    if (!currentAccountId || profilesLoading) return
    setLoading(true); setError(null)
    try {
      const [scheds, camps] = await Promise.all([
        // Schedules belong to one marketplace. With "All Profiles" selected,
        // ask every profile rather than silently picking the first.
        Promise.all(
          (currentProfileId ? [currentProfileId] : Array.from(accountProfileIds))
            .map(pid => api.listDaypartingSchedules(pid)),
        ).then(b => b.flat()),
        api.listCampaigns(),
      ])
      setSchedules(scheds)
      setCampaigns(camps)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load schedules')
    } finally {
      setLoading(false)
    }
  }, [currentAccountId, currentProfileId, accountProfileIds, profilesLoading])

  useEffect(() => {
    if (user && !accountsLoading && !profilesLoading) load()
  }, [user, accountsLoading, profilesLoading, load])

  function notify(msg: string, isErr = false) {
    if (isErr) { setToastErr(msg); setTimeout(() => setToastErr(null), 6000) }
    else       { setToast(msg);    setTimeout(() => setToast(null), 6000) }
  }

  const campaignName = useCallback(
    (id: string) => campaigns.find(c => c.id === id)?.name ?? '—',
    [campaigns],
  )

  async function activate(s: DaypartingSchedule) {
    const names = s.campaign_ids.map(campaignName).join(', ')
    const ok = window.confirm(
      `Activate "${s.name}"?\n\n` +
      `From now on this will pause and re-enable these campaigns automatically, ` +
      `without asking each time:\n\n${names}\n\n` +
      `It checks hourly and corrects anything that does not match the schedule.`,
    )
    if (!ok) return
    try {
      const updated = await api.activateDaypartingSchedule(s.id)
      setSchedules(list => list.map(x => x.id === updated.id ? updated : x))
      notify(`"${s.name}" is now active and running hourly`)
    } catch (e) {
      notify(e instanceof ApiError ? e.message : 'Could not activate', true)
    }
  }

  async function deactivate(s: DaypartingSchedule) {
    try {
      const updated = await api.deactivateDaypartingSchedule(s.id)
      setSchedules(list => list.map(x => x.id === updated.id ? updated : x))
      notify(`"${s.name}" stopped. Campaigns were left exactly as they are now.`)
    } catch (e) {
      notify(e instanceof ApiError ? e.message : 'Could not deactivate', true)
    }
  }

  async function remove(s: DaypartingSchedule) {
    if (!window.confirm(`Delete "${s.name}"? Campaigns keep their current state.`)) return
    try {
      await api.deleteDaypartingSchedule(s.id)
      setSchedules(list => list.filter(x => x.id !== s.id))
      notify(`"${s.name}" deleted`)
    } catch (e) {
      notify(e instanceof ApiError ? e.message : 'Could not delete', true)
    }
  }

  async function preview(s: DaypartingSchedule) {
    try {
      const r = await api.runDaypartingNow(s.id)
      if (r.dry_run) {
        // Report the bid intent too. A schedule made only of bid windows has
        // no desired state at any hour, so showing state alone said
        // "no change" and read as "this schedule does nothing".
        // Map the stored state to a verb phrase. Interpolating the raw value
        // produced "wants to paused".
        const state = r.would_set_state === 'paused' ? 'pause these campaigns'
          : r.would_set_state === 'enabled' ? 'enable these campaigns'
          : 'leave the on/off state alone'
        const bids = r.would_adjust_bids
        notify(
          `At ${r.local_time}, this schedule wants to ${state}` +
          (bids ? `, and ${bids}` : '') +
          `. Nothing was sent — it is not active.`,
        )
      } else {
        notify(`Checked ${r.checked}, changed ${r.changed}, skipped ${r.skipped}, failed ${r.failed}`)
      }
    } catch (e) {
      notify(e instanceof ApiError ? e.message : 'Could not run', true)
    }
  }

  if (authLoading || accountsLoading) return <LoadingState message="Loading…" />
  if (!user) return null
  if (error) return <ErrorState message={error} onRetry={load} />

  const activeCount = schedules.filter(s => s.is_active).length

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <PageHeader
          title="Dayparting"
          subtitle="Pause, re-enable, or adjust bids by hour and weekday. You choose the hours."
        />
        <button className="btn-primary" onClick={() => setEditing('new')}>
          + New Schedule
        </button>
      </div>

      {activeCount > 0 && (
        <div className="rounded-xl border border-accent-edge bg-accent-weak p-3 text-sm text-accent">
          <span className="font-medium">
            {activeCount} schedule{activeCount === 1 ? '' : 's'} running.
          </span>{' '}
          These change campaign state automatically every hour without asking.
          This is the only part of the app that does that.
        </div>
      )}

      {toast && <Notice tone="ok">{toast}</Notice>}
      {toastErr && <Notice tone="danger">{toastErr}</Notice>}

      {loading && schedules.length === 0 ? (
        <div className="card text-center py-12 text-ink-subtle">Loading…</div>
      ) : schedules.length === 0 ? (
        <div className="card text-center py-14">
          <p className="text-ink-muted mb-1">No schedules yet</p>
          <p className="text-sm text-ink-subtle mb-4 max-w-md mx-auto">
            A schedule turns campaigns off during hours you choose — for example
            midnight to 6am on weekdays — and back on afterwards.
          </p>
          <button className="btn-primary text-sm" onClick={() => setEditing('new')}>
            Create your first schedule
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {schedules.map(s => (
            <div key={s.id} className="card">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold text-ink">{s.name}</h3>
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                      s.is_active ? 'bg-info-tint text-accent' : 'bg-surface-sunken text-ink-muted'
                    }`}>
                      {s.is_active ? 'running' : 'stopped'}
                    </span>
                  </div>
                  {s.description && <p className="text-sm text-ink-muted mt-0.5">{s.description}</p>}
                  <p className="text-xs text-ink-subtle mt-1">
                    {s.campaign_ids.length} campaign{s.campaign_ids.length === 1 ? '' : 's'} ·{' '}
                    {s.entries.length} window{s.entries.length === 1 ? '' : 's'}
                    {s.activated_at && ` · started ${new Date(s.activated_at).toLocaleDateString()}`}
                  </p>
                </div>
                {/* Two visible actions, the rest in a menu.
                    Delete used to sit immediately beside Activate — and Activate
                    is the one control in this whole app that starts changing a
                    live ad account with nobody watching. Those two should not be
                    neighbours. Dry-run stays visible because it is what you do
                    BEFORE activating, and Activate stays visible because hiding a
                    consequential action in a menu is its own kind of trap. */}
                <div className="flex shrink-0 items-center gap-1.5">
                  <Button size="sm" variant="secondary" onClick={() => preview(s)}>
                    <Eye aria-hidden />
                    Dry run
                  </Button>
                  {s.is_active ? (
                    <Button size="sm" variant="danger" onClick={() => deactivate(s)}>
                      <Square aria-hidden />
                      Stop
                    </Button>
                  ) : (
                    <Button size="sm" variant="primary" onClick={() => activate(s)}>
                      <Play aria-hidden />
                      Activate
                    </Button>
                  )}
                  <RowMenu label={`Actions for ${s.name}`}>
                    <MenuItem onSelect={() => setEditing(s)}>
                      <Pencil aria-hidden /> Edit schedule
                    </MenuItem>
                    <MenuItem onSelect={() => setRunsFor(s)}>
                      <History aria-hidden /> Run history
                    </MenuItem>
                    <MenuSeparator />
                    <MenuItem danger onSelect={() => remove(s)}>
                      <Trash2 aria-hidden /> Delete schedule
                    </MenuItem>
                  </RowMenu>
                </div>
              </div>
              <ScheduleGridPreview schedule={s} />
              <p className="text-xs text-ink-subtle mt-2">
                Campaigns: {s.campaign_ids.map(campaignName).join(', ') || '—'}
              </p>
            </div>
          ))}
        </div>
      )}

      <p className="text-xs text-ink-subtle">
        Hours are local to the marketplace. Outside its windows a schedule puts
        back what it changed — so you only need to mark the hours you want
        paused. It never switches on a campaign you paused yourself, because it
        only ever undoes its own changes.
      </p>

      {editing && (
        <ScheduleEditor
          schedule={editing === 'new' ? null : editing}
          campaigns={campaigns}
          defaultProfileId={currentProfileId ?? profiles[0]?.id ?? ''}
          profiles={profiles}
          onClose={() => setEditing(null)}
          onSaved={s => {
            setSchedules(list => {
              const exists = list.some(x => x.id === s.id)
              return exists ? list.map(x => x.id === s.id ? s : x) : [s, ...list]
            })
            setEditing(null)
            notify(`"${s.name}" saved. It is not running until you activate it.`)
          }}
        />
      )}

      {runsFor && <RunHistoryDrawer schedule={runsFor} onClose={() => setRunsFor(null)} />}
    </div>
  )
}


/**
 * A painted cell has to carry more than "pause" now: a bid window also has a
 * percentage and optional min/max. So a cell holds a SPEC STRING encoding the
 * whole action.
 *
 *   pause | enable | decrease_bid:20:0.18: | increase_bid:50::1.20
 *
 * Encoding it as a string keeps the run-merging in toEntries() a plain
 * equality check, so two adjacent hours only merge into one window when they
 * agree on the percentage and the limits as well as the action — painting
 * -10% in the morning and -20% in the afternoon correctly produces two
 * windows rather than one wrong one.
 */
type CellSpec = string

function makeSpec(
  action: string, pct: string, minBid: string, maxBid: string,
): CellSpec {
  if (action !== 'decrease_bid' && action !== 'increase_bid') return action
  return `${action}:${pct}:${minBid}:${maxBid}`
}

function parseSpec(spec: CellSpec) {
  const [action, pct, minBid, maxBid] = spec.split(':')
  const isBid = action === 'decrease_bid' || action === 'increase_bid'
  return {
    action_type: action,
    adjust_pct: isBid && pct ? Number(pct) : null,
    min_bid: isBid && minBid ? Number(minBid) : null,
    max_bid: isBid && maxBid ? Number(maxBid) : null,
  }
}

/** Colour per action. Amber for down, blue for up — money leaving vs money spent. */
function specColour(spec: CellSpec | undefined, filled: boolean): string {
  const action = spec?.split(':')[0]
  if (action === 'pause') return filled ? 'bg-danger border-danger' : 'bg-danger'
  if (action === 'enable') return filled ? 'bg-ok border-ok' : 'bg-ok'
  if (action === 'decrease_bid') return filled ? 'bg-warn border-warn' : 'bg-warn'
  if (action === 'increase_bid') return filled ? 'bg-accent border-accent' : 'bg-accent'
  return filled ? 'bg-surface border-hairline hover:border-line-strong' : 'bg-surface-sunken'
}

function specLabel(spec: CellSpec | undefined): string {
  if (!spec) return 'untouched'
  const { action_type, adjust_pct, min_bid, max_bid } = parseSpec(spec)
  if (action_type === 'pause') return 'paused'
  if (action_type === 'enable') return 'enabled'
  const dir = action_type === 'decrease_bid' ? '−' : '+'
  const limits = [
    min_bid ? `min $${min_bid}` : '',
    max_bid ? `max $${max_bid}` : '',
  ].filter(Boolean).join(', ')
  return `bid ${dir}${adjust_pct}% from baseline${limits ? ` (${limits})` : ''}`
}

// ── Read-only grid summary ────────────────────────────────────────────────

function ScheduleGridPreview({ schedule }: { schedule: DaypartingSchedule }) {
  // Map rather than Set: the cell needs the whole spec to colour and label
  // itself, not merely "is something set here".
  const filled = useMemo(() => {
    const map = new Map<string, CellSpec>()
    for (const e of schedule.entries) {
      const spec = makeSpec(
        e.action_type,
        e.adjust_pct != null ? String(e.adjust_pct) : '',
        e.min_bid != null ? String(e.min_bid) : '',
        e.max_bid != null ? String(e.max_bid) : '',
      )
      for (let h = e.hour_start; h < e.hour_end; h++) {
        map.set(`${e.day_of_week}-${h}`, spec)
      }
    }
    return map
  }, [schedule.entries])

  return (
    <div className="mt-3 overflow-x-auto">
      <div className="inline-block">
        <div className="flex gap-[2px] mb-[2px] ml-9">
          {HOURS.map(h => (
            <div key={h} className="w-3.5 text-[9px] text-ink-subtle text-center">
              {h % 6 === 0 ? hourLabel(h).replace('am', '').replace('pm', '') : ''}
            </div>
          ))}
        </div>
        {DAYS.map((day, dow) => (
          <div key={day} className="flex gap-[2px] mb-[2px] items-center">
            <div className="w-9 text-[10px] text-ink-muted">{day}</div>
            {HOURS.map(h => {
              const spec = filled.get(`${dow}-${h}`)
              return (
                <div
                  key={h}
                  title={`${day} ${hourLabel(h)} — ${specLabel(spec)}`}
                  className={`w-3.5 h-3.5 rounded-sm ${specColour(spec, false)}`}
                />
              )
            })}
          </div>
        ))}
        <div className="flex gap-3 mt-1.5 ml-9 text-[10px] text-ink-muted">
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-danger inline-block" /> paused</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-ok inline-block" /> enabled</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-warn inline-block" /> bid down</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-accent inline-block" /> bid up</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-surface-sunken inline-block" /> normal (restored)</span>
        </div>
      </div>
    </div>
  )
}

// ── Editor ────────────────────────────────────────────────────────────────

function ScheduleEditor({
  schedule, campaigns, defaultProfileId, profiles, onClose, onSaved,
}: {
  schedule: DaypartingSchedule | null
  campaigns: Campaign[]
  defaultProfileId: string
  profiles: { id: string; country_code: string | null; marketplace_code: string }[]
  onClose: () => void
  onSaved: (s: DaypartingSchedule) => void
}) {
  const [name, setName] = useState(schedule?.name ?? '')
  const [description, setDescription] = useState(schedule?.description ?? '')
  const [profileId, setProfileId] = useState(schedule?.profile_id ?? defaultProfileId)
  const [selected, setSelected] = useState<Set<string>>(new Set(schedule?.campaign_ids ?? []))
  const [action, setAction] =
    useState<'pause' | 'enable' | 'decrease_bid' | 'increase_bid'>('pause')
  // Bid parameters for the brush. Kept as strings so a half-typed "1." does
  // not become NaN mid-keystroke.
  const [pct, setPct] = useState('20')
  const [minBid, setMinBid] = useState('')
  const [maxBid, setMaxBid] = useState('')
  const isBidAction = action === 'decrease_bid' || action === 'increase_bid'
  const brush = makeSpec(action, pct, minBid, maxBid)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /** cellKey `${dow}-${hour}` → spec. One action per cell; last paint wins. */
  const [cells, setCells] = useState<Map<string, CellSpec>>(() => {
    const m = new Map<string, CellSpec>()
    for (const e of schedule?.entries ?? []) {
      // 'bid_adjust' from the original schema has no executor and the API
      // rejects it, so an old row is dropped rather than shown as editable.
      if (!['pause', 'enable', 'decrease_bid', 'increase_bid'].includes(e.action_type)) continue
      const spec = makeSpec(
        e.action_type,
        e.adjust_pct != null ? String(e.adjust_pct) : '',
        e.min_bid != null ? String(e.min_bid) : '',
        e.max_bid != null ? String(e.max_bid) : '',
      )
      for (let h = e.hour_start; h < e.hour_end; h++) {
        m.set(`${e.day_of_week}-${h}`, spec)
      }
    }
    return m
  })

  const eligible = useMemo(
    () => campaigns.filter(c => c.profile_id === profileId),
    [campaigns, profileId],
  )

  function toggleCell(dow: number, hour: number) {
    setCells(prev => {
      const next = new Map(prev)
      const key = `${dow}-${hour}`
      if (next.get(key) === brush) next.delete(key)
      else next.set(key, brush)
      return next
    })
  }

  function paintRow(dow: number, hours: number[]) {
    setCells(prev => {
      const next = new Map(prev)
      const allSet = hours.every(h => next.get(`${dow}-${h}`) === brush)
      for (const h of hours) {
        if (allSet) next.delete(`${dow}-${h}`)
        else next.set(`${dow}-${h}`, brush)
      }
      return next
    })
  }

  /**
   * Collapse painted cells into contiguous windows.
   *
   * The API enforces hour_end > hour_start, so a run that reaches midnight
   * simply ends at 24 on that day. An overnight span is naturally two entries
   * on adjacent days, which is exactly what the executor expects.
   */
  function toEntries() {
    const out: DaypartingEntryInput[] = []
    for (let dow = 0; dow < 7; dow++) {
      let runStart: number | null = null
      let runSpec: CellSpec | null = null
      for (let h = 0; h <= 24; h++) {
        const a = h < 24 ? cells.get(`${dow}-${h}`) ?? null : null
        // Equality on the whole spec, so -10% and -20% never merge into one
        // window even when the hours are adjacent.
        if (a !== runSpec) {
          if (runSpec !== null && runStart !== null) {
            out.push({
              day_of_week: dow, hour_start: runStart, hour_end: h,
              ...parseSpec(runSpec),
            })
          }
          runStart = a === null ? null : h
          runSpec = a
        }
      }
    }
    return out
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const entries = toEntries()
    if (entries.length === 0) { setError('Paint at least one hour on the grid'); return }
    if (selected.size === 0) { setError('Select at least one campaign'); return }
    setSaving(true); setError(null)
    try {
      const body = {
        profile_id: profileId,
        name: name.trim(),
        description: description.trim() || null,
        campaign_ids: Array.from(selected),
        entries,
      }
      const saved = schedule
        ? await api.updateDaypartingSchedule(schedule.id, body)
        : await api.createDaypartingSchedule(body)
      onSaved(saved as DaypartingSchedule)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save schedule')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 p-4">
      <div className="bg-surface rounded-xl shadow-xl w-full max-w-4xl max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-hairline">
          <h2 className="font-semibold text-ink">
            {schedule ? 'Edit schedule' : 'New schedule'}
          </h2>
          <button onClick={onClose} className="text-ink-subtle hover:text-ink-muted text-xl leading-none">×</button>
        </div>

        <form onSubmit={submit} className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-ink mb-1">Name <span className="text-danger">*</span></label>
              <input className="input w-full" value={name} onChange={e => setName(e.target.value)}
                     placeholder="e.g. Overnight pause" required />
            </div>
            <div>
              <label className="block text-sm font-medium text-ink mb-1">Marketplace</label>
              <select className="input w-full" value={profileId}
                      onChange={e => { setProfileId(e.target.value); setSelected(new Set()) }}
                      disabled={!!schedule}>
                {profiles.map(p => (
                  <option key={p.id} value={p.id}>{p.country_code ?? p.marketplace_code}</option>
                ))}
              </select>
              {schedule && <p className="text-xs text-ink-subtle mt-1">Cannot move a schedule between marketplaces.</p>}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-ink mb-1">Description</label>
            <input className="input w-full" value={description} onChange={e => setDescription(e.target.value)}
                   placeholder="Optional note for your team" />
          </div>

          {/* Grid */}
          <div>
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
              <label className="block text-sm font-medium text-ink">
                Hours <span className="text-danger">*</span>
              </label>
              <div className="flex items-center gap-2 text-xs flex-wrap">
                <span className="text-ink-muted">Painting:</span>
                <button type="button" onClick={() => setAction('pause')}
                        className={`px-2 py-1 rounded border ${action === 'pause'
                          ? 'bg-danger-tint0 text-white border-danger' : 'bg-surface border-line'}`}>
                  Pause campaign
                </button>
                <button type="button" onClick={() => setAction('enable')}
                        className={`px-2 py-1 rounded border ${action === 'enable'
                          ? 'bg-ok text-white border-ok' : 'bg-surface border-line'}`}>
                  Enable campaign
                </button>
                <button type="button" onClick={() => setAction('decrease_bid')}
                        className={`px-2 py-1 rounded border ${action === 'decrease_bid'
                          ? 'bg-warn-tint0 text-white border-warn' : 'bg-surface border-line'}`}>
                  Decrease bid
                </button>
                <button type="button" onClick={() => setAction('increase_bid')}
                        className={`px-2 py-1 rounded border ${action === 'increase_bid'
                          ? 'bg-accent text-white border-accent' : 'bg-surface border-line'}`}>
                  Increase bid
                </button>
              </div>
            </div>

            {isBidAction && (
              <div className="mb-2 p-3 rounded-lg bg-warn-tint border border-warn/20">
                <div className="flex items-end gap-3 flex-wrap text-xs">
                  <label className="block">
                    <span className="block text-ink-muted mb-1">
                      {action === 'decrease_bid' ? 'Decrease by' : 'Increase by'} *
                    </span>
                    <div className="flex items-center gap-1">
                      <input type="number" min="0.01" max={action === 'decrease_bid' ? '99.99' : '900'}
                             step="1" value={pct} onChange={e => setPct(e.target.value)}
                             className="input w-20" />
                      <span className="text-ink-muted">%</span>
                    </div>
                  </label>
                  <label className="block">
                    <span className="block text-ink-muted mb-1">Min bid</span>
                    <input type="number" min="0.02" step="0.01" placeholder="none"
                           value={minBid} onChange={e => setMinBid(e.target.value)}
                           className="input w-24" />
                  </label>
                  <label className="block">
                    <span className="block text-ink-muted mb-1">Max bid</span>
                    <input type="number" min="0.02" step="0.01" placeholder="none"
                           value={maxBid} onChange={e => setMaxBid(e.target.value)}
                           className="input w-24" />
                  </label>
                </div>
                <p className="text-[11px] text-warn mt-2 leading-relaxed">
                  Applied to each keyword&apos;s <strong>baseline bid</strong> — the bid it
                  had before this schedule touched it — not to the current bid, so it
                  never compounds. Outside these hours the baseline is restored.
                  Change the percentage and paint again to add a second, different
                  window on the same day.
                </p>
                <p className="text-[11px] text-warn mt-1 leading-relaxed">
                  If someone edits a bid in Seller Central, this schedule stops
                  managing that keyword and notifies you rather than overwriting them.
                </p>
              </div>
            )}

            <div className="overflow-x-auto border border-hairline rounded-lg p-3">
              <div className="inline-block">
                <div className="flex gap-[2px] mb-1 ml-24">
                  {HOURS.map(h => (
                    <div key={h} className="w-5 text-[9px] text-ink-subtle text-center">
                      {h % 3 === 0 ? hourLabel(h) : ''}
                    </div>
                  ))}
                </div>
                {DAYS.map((day, dow) => (
                  <div key={day} className="flex gap-[2px] mb-[2px] items-center">
                    <div className="w-24 flex items-center gap-1">
                      <span className="text-xs text-ink-muted w-8">{day}</span>
                      <button type="button" onClick={() => paintRow(dow, HOURS)}
                              className="text-[9px] text-accent hover:underline">all</button>
                      <button type="button" onClick={() => paintRow(dow, [0, 1, 2, 3, 4, 5])}
                              className="text-[9px] text-accent hover:underline">0-6</button>
                    </div>
                    {HOURS.map(h => {
                      const v = cells.get(`${dow}-${h}`)
                      return (
                        <button
                          key={h}
                          type="button"
                          onClick={() => toggleCell(dow, h)}
                          title={`${day} ${hourLabel(h)} — ${specLabel(v)}`}
                          className={`w-5 h-5 rounded-sm border ${specColour(v, true)}`}
                        />
                      )
                    })}
                  </div>
                ))}
              </div>
            </div>
            <p className="text-xs text-ink-subtle mt-1.5">
              Mark <span className="font-medium">12am–6am</span> as paused and ads are
              off from midnight and back on at 6am exactly — you do{' '}
              <span className="font-medium">not</span> need to mark the rest of the day
              as enabled. Outside its windows the schedule restores whatever it
              changed. &ldquo;Enable campaign&rdquo; is there for the rare case where you
              want a campaign switched on at a set hour regardless of how it was
              left.
            </p>
          </div>

          {/* Campaigns */}
          <div>
            <label className="block text-sm font-medium text-ink mb-1">
              Campaigns <span className="text-danger">*</span>
              <span className="text-xs font-normal text-ink-subtle ml-2">{selected.size} selected</span>
            </label>
            <div className="border border-hairline rounded-lg max-h-44 overflow-y-auto divide-y divide-hairline">
              {eligible.length === 0 ? (
                <p className="text-sm text-ink-subtle p-3">No campaigns in this marketplace.</p>
              ) : eligible.map(c => (
                <label key={c.id} className="flex items-center gap-2 px-3 py-2 hover:bg-surface-sunken cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selected.has(c.id)}
                    onChange={e => setSelected(prev => {
                      const next = new Set(prev)
                      if (e.target.checked) next.add(c.id); else next.delete(c.id)
                      return next
                    })}
                  />
                  <span className="text-sm text-ink truncate flex-1">{c.name}</span>
                  <span className="text-xs text-ink-subtle">{c.status}</span>
                </label>
              ))}
            </div>
          </div>

          {error && <Notice tone="danger">{error}</Notice>}
        </form>

        <div className="flex items-center justify-between px-6 py-4 border-t border-hairline">
          <p className="text-xs text-ink-muted">
            Saving does not start it. You activate it separately.
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={onClose}
                    className="px-4 py-2 text-sm border border-line rounded hover:bg-surface-sunken">
              Cancel
            </button>
            <button onClick={submit} disabled={saving} className="btn-primary disabled:opacity-50">
              {saving ? 'Saving…' : 'Save schedule'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Run history ───────────────────────────────────────────────────────────

function RunHistoryDrawer({
  schedule, onClose,
}: { schedule: DaypartingSchedule; onClose: () => void }) {
  const [runs, setRuns] = useState<DaypartingRun[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.listDaypartingRuns(schedule.id).then(setRuns).finally(() => setLoading(false))
  }, [schedule.id])

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/20" onClick={onClose} />
      <div className="relative w-full max-w-lg bg-surface shadow-xl flex flex-col overflow-y-auto">
        <div className="flex items-start justify-between px-5 py-4 border-b border-hairline sticky top-0 bg-surface">
          <div>
            <p className="text-xs text-ink-subtle mb-1">Run history</p>
            <h2 className="text-base font-semibold text-ink">{schedule.name}</h2>
            <p className="text-xs text-ink-subtle mt-0.5">
              Every hourly check, including the ones where nothing needed changing.
            </p>
          </div>
          <button onClick={onClose} className="text-ink-subtle hover:text-ink-muted text-xl leading-none">×</button>
        </div>
        <div className="divide-y divide-hairline">
          {loading ? (
            <p className="p-5 text-sm text-ink-subtle text-center">Loading…</p>
          ) : runs.length === 0 ? (
            <p className="p-5 text-sm text-ink-subtle text-center">
              Nothing yet. Runs appear once the schedule is active, or when you
              use &quot;What would it do now?&quot;.
            </p>
          ) : runs.map(r => (
            <div key={r.id} className="px-5 py-3">
              <div className="flex items-center justify-between gap-2">
                <span className={`text-xs px-2 py-0.5 rounded font-medium ${OUTCOME_STYLE[r.outcome] ?? 'bg-surface-sunken text-ink-muted'}`}>
                  {outcomeLabel(r.outcome)}
                </span>
                <span className="text-xs text-ink-subtle">{r.local_time ?? new Date(r.ran_at).toLocaleString()}</span>
              </div>
              {r.desired_state && (
                <p className="text-xs text-ink mt-1.5">
                  wanted <span className="font-medium">{r.desired_state}</span>
                  {r.previous_state && <> · was <span className="font-medium">{r.previous_state}</span></>}
                </p>
              )}
              {r.detail && <p className="text-xs text-ink-muted mt-1">{r.detail}</p>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

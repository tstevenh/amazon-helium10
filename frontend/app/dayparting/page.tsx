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
import { api, ApiError } from '@/lib/api'
import type { Campaign, DaypartingSchedule, DaypartingRun } from '@/lib/types'
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
  applied: 'bg-blue-100 text-blue-700',
  already_correct: 'bg-gray-100 text-gray-600',
  skipped_writes_disabled: 'bg-yellow-100 text-yellow-800',
  skipped_no_timezone: 'bg-yellow-100 text-yellow-800',
  failed: 'bg-red-100 text-red-700',
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
        const state = r.would_set_state ?? 'no change'
        notify(`At ${r.local_time}, this schedule wants: ${state}. Nothing was sent — it is not active.`)
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
          subtitle="Pause and re-enable campaigns by hour. You choose the hours."
        />
        <button className="btn-primary" onClick={() => setEditing('new')}>
          + New Schedule
        </button>
      </div>

      {activeCount > 0 && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
          <span className="font-medium">
            {activeCount} schedule{activeCount === 1 ? '' : 's'} running.
          </span>{' '}
          These change campaign state automatically every hour without asking.
          This is the only part of the app that does that.
        </div>
      )}

      {toast && <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2 text-sm text-green-700">✓ {toast}</div>}
      {toastErr && <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-2 text-sm text-red-700">✗ {toastErr}</div>}

      {loading && schedules.length === 0 ? (
        <div className="card text-center py-12 text-gray-400">Loading…</div>
      ) : schedules.length === 0 ? (
        <div className="card text-center py-14">
          <p className="text-gray-500 mb-1">No schedules yet</p>
          <p className="text-sm text-gray-400 mb-4 max-w-md mx-auto">
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
                    <h3 className="font-semibold text-gray-900">{s.name}</h3>
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                      s.is_active ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-600'
                    }`}>
                      {s.is_active ? 'running' : 'stopped'}
                    </span>
                  </div>
                  {s.description && <p className="text-sm text-gray-500 mt-0.5">{s.description}</p>}
                  <p className="text-xs text-gray-400 mt-1">
                    {s.campaign_ids.length} campaign{s.campaign_ids.length === 1 ? '' : 's'} ·{' '}
                    {s.entries.length} window{s.entries.length === 1 ? '' : 's'}
                    {s.activated_at && ` · started ${new Date(s.activated_at).toLocaleDateString()}`}
                  </p>
                </div>
                <div className="flex gap-2 flex-wrap">
                  <button onClick={() => preview(s)} className="text-xs px-2.5 py-1 bg-white border border-gray-300 rounded hover:bg-gray-50">
                    What would it do now?
                  </button>
                  <button onClick={() => setRunsFor(s)} className="text-xs px-2.5 py-1 bg-white border border-gray-300 rounded hover:bg-gray-50">
                    History
                  </button>
                  <button onClick={() => setEditing(s)} className="text-xs px-2.5 py-1 bg-white border border-gray-300 rounded hover:bg-gray-50">
                    Edit
                  </button>
                  {s.is_active ? (
                    <button onClick={() => deactivate(s)} className="text-xs px-2.5 py-1 bg-white border border-red-200 text-red-600 rounded hover:bg-red-50">
                      Stop
                    </button>
                  ) : (
                    <button onClick={() => activate(s)} className="text-xs px-2.5 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
                      Activate
                    </button>
                  )}
                  <button onClick={() => remove(s)} className="text-xs px-2 py-1 bg-white border border-red-200 text-red-500 rounded hover:bg-red-50">
                    ✕
                  </button>
                </div>
              </div>
              <ScheduleGridPreview schedule={s} />
              <p className="text-xs text-gray-400 mt-2">
                Campaigns: {s.campaign_ids.map(campaignName).join(', ') || '—'}
              </p>
            </div>
          ))}
        </div>
      )}

      <p className="text-xs text-gray-400">
        Hours are local to the marketplace. Outside every window a campaign is
        left alone — a schedule never switches on something you paused yourself.
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

// ── Read-only grid summary ────────────────────────────────────────────────

function ScheduleGridPreview({ schedule }: { schedule: DaypartingSchedule }) {
  const filled = useMemo(() => {
    const set = new Set<string>()
    for (const e of schedule.entries) {
      for (let h = e.hour_start; h < e.hour_end; h++) {
        set.add(`${e.day_of_week}-${h}-${e.action_type}`)
      }
    }
    return set
  }, [schedule.entries])

  return (
    <div className="mt-3 overflow-x-auto">
      <div className="inline-block">
        <div className="flex gap-[2px] mb-[2px] ml-9">
          {HOURS.map(h => (
            <div key={h} className="w-3.5 text-[9px] text-gray-400 text-center">
              {h % 6 === 0 ? hourLabel(h).replace('am', '').replace('pm', '') : ''}
            </div>
          ))}
        </div>
        {DAYS.map((day, dow) => (
          <div key={day} className="flex gap-[2px] mb-[2px] items-center">
            <div className="w-9 text-[10px] text-gray-500">{day}</div>
            {HOURS.map(h => {
              const paused = filled.has(`${dow}-${h}-pause`)
              const enabled = filled.has(`${dow}-${h}-enable`)
              return (
                <div
                  key={h}
                  title={`${day} ${hourLabel(h)} — ${paused ? 'paused' : enabled ? 'enabled' : 'untouched'}`}
                  className={`w-3.5 h-3.5 rounded-sm ${
                    paused ? 'bg-red-400' : enabled ? 'bg-green-400' : 'bg-gray-100'
                  }`}
                />
              )
            })}
          </div>
        ))}
        <div className="flex gap-3 mt-1.5 ml-9 text-[10px] text-gray-500">
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-red-400 inline-block" /> paused</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-green-400 inline-block" /> enabled</span>
          <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm bg-gray-100 inline-block" /> left alone</span>
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
  const [action, setAction] = useState<'pause' | 'enable'>('pause')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /** cellKey `${dow}-${hour}` → action. One action per cell; last paint wins. */
  const [cells, setCells] = useState<Map<string, 'pause' | 'enable'>>(() => {
    const m = new Map<string, 'pause' | 'enable'>()
    for (const e of schedule?.entries ?? []) {
      if (e.action_type !== 'pause' && e.action_type !== 'enable') continue
      for (let h = e.hour_start; h < e.hour_end; h++) {
        m.set(`${e.day_of_week}-${h}`, e.action_type as 'pause' | 'enable')
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
      if (next.get(key) === action) next.delete(key)
      else next.set(key, action)
      return next
    })
  }

  function paintRow(dow: number, hours: number[]) {
    setCells(prev => {
      const next = new Map(prev)
      const allSet = hours.every(h => next.get(`${dow}-${h}`) === action)
      for (const h of hours) {
        if (allSet) next.delete(`${dow}-${h}`)
        else next.set(`${dow}-${h}`, action)
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
    const out: { day_of_week: number; hour_start: number; hour_end: number; action_type: string }[] = []
    for (let dow = 0; dow < 7; dow++) {
      let runStart: number | null = null
      let runAction: 'pause' | 'enable' | null = null
      for (let h = 0; h <= 24; h++) {
        const a = h < 24 ? cells.get(`${dow}-${h}`) ?? null : null
        if (a !== runAction) {
          if (runAction !== null && runStart !== null) {
            out.push({ day_of_week: dow, hour_start: runStart, hour_end: h, action_type: runAction })
          }
          runStart = a === null ? null : h
          runAction = a
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
      <div className="bg-white rounded-xl shadow-xl w-full max-w-4xl max-h-[92vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="font-semibold text-gray-900">
            {schedule ? 'Edit schedule' : 'New schedule'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <form onSubmit={submit} className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Name <span className="text-red-500">*</span></label>
              <input className="input w-full" value={name} onChange={e => setName(e.target.value)}
                     placeholder="e.g. Overnight pause" required />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Marketplace</label>
              <select className="input w-full" value={profileId}
                      onChange={e => { setProfileId(e.target.value); setSelected(new Set()) }}
                      disabled={!!schedule}>
                {profiles.map(p => (
                  <option key={p.id} value={p.id}>{p.country_code ?? p.marketplace_code}</option>
                ))}
              </select>
              {schedule && <p className="text-xs text-gray-400 mt-1">Cannot move a schedule between marketplaces.</p>}
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <input className="input w-full" value={description} onChange={e => setDescription(e.target.value)}
                   placeholder="Optional note for your team" />
          </div>

          {/* Grid */}
          <div>
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
              <label className="block text-sm font-medium text-gray-700">
                Hours <span className="text-red-500">*</span>
              </label>
              <div className="flex items-center gap-2 text-xs">
                <span className="text-gray-500">Painting:</span>
                <button type="button" onClick={() => setAction('pause')}
                        className={`px-2 py-1 rounded border ${action === 'pause'
                          ? 'bg-red-500 text-white border-red-500' : 'bg-white border-gray-300'}`}>
                  Pause
                </button>
                <button type="button" onClick={() => setAction('enable')}
                        className={`px-2 py-1 rounded border ${action === 'enable'
                          ? 'bg-green-600 text-white border-green-600' : 'bg-white border-gray-300'}`}>
                  Enable
                </button>
              </div>
            </div>

            <div className="overflow-x-auto border border-gray-200 rounded-lg p-3">
              <div className="inline-block">
                <div className="flex gap-[2px] mb-1 ml-24">
                  {HOURS.map(h => (
                    <div key={h} className="w-5 text-[9px] text-gray-400 text-center">
                      {h % 3 === 0 ? hourLabel(h) : ''}
                    </div>
                  ))}
                </div>
                {DAYS.map((day, dow) => (
                  <div key={day} className="flex gap-[2px] mb-[2px] items-center">
                    <div className="w-24 flex items-center gap-1">
                      <span className="text-xs text-gray-600 w-8">{day}</span>
                      <button type="button" onClick={() => paintRow(dow, HOURS)}
                              className="text-[9px] text-blue-600 hover:underline">all</button>
                      <button type="button" onClick={() => paintRow(dow, [0, 1, 2, 3, 4, 5])}
                              className="text-[9px] text-blue-600 hover:underline">0-6</button>
                    </div>
                    {HOURS.map(h => {
                      const v = cells.get(`${dow}-${h}`)
                      return (
                        <button
                          key={h}
                          type="button"
                          onClick={() => toggleCell(dow, h)}
                          title={`${day} ${hourLabel(h)}`}
                          className={`w-5 h-5 rounded-sm border ${
                            v === 'pause' ? 'bg-red-400 border-red-400'
                              : v === 'enable' ? 'bg-green-400 border-green-400'
                              : 'bg-white border-gray-200 hover:border-gray-400'
                          }`}
                        />
                      )
                    })}
                  </div>
                ))}
              </div>
            </div>
            <p className="text-xs text-gray-400 mt-1.5">
              An hour marked at <span className="font-medium">12am–6am</span> means ads
              are off from midnight and back on at 6am exactly. Unpainted hours are
              left untouched.
            </p>
          </div>

          {/* Campaigns */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Campaigns <span className="text-red-500">*</span>
              <span className="text-xs font-normal text-gray-400 ml-2">{selected.size} selected</span>
            </label>
            <div className="border border-gray-200 rounded-lg max-h-44 overflow-y-auto divide-y divide-gray-100">
              {eligible.length === 0 ? (
                <p className="text-sm text-gray-400 p-3">No campaigns in this marketplace.</p>
              ) : eligible.map(c => (
                <label key={c.id} className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selected.has(c.id)}
                    onChange={e => setSelected(prev => {
                      const next = new Set(prev)
                      if (e.target.checked) next.add(c.id); else next.delete(c.id)
                      return next
                    })}
                  />
                  <span className="text-sm text-gray-800 truncate flex-1">{c.name}</span>
                  <span className="text-xs text-gray-400">{c.status}</span>
                </label>
              ))}
            </div>
          </div>

          {error && <div className="bg-red-50 border border-red-200 rounded px-3 py-2 text-sm text-red-700">{error}</div>}
        </form>

        <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200">
          <p className="text-xs text-gray-500">
            Saving does not start it. You activate it separately.
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={onClose}
                    className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">
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
      <div className="relative w-full max-w-lg bg-white shadow-xl flex flex-col overflow-y-auto">
        <div className="flex items-start justify-between px-5 py-4 border-b border-gray-200 sticky top-0 bg-white">
          <div>
            <p className="text-xs text-gray-400 mb-1">Run history</p>
            <h2 className="text-base font-semibold text-gray-900">{schedule.name}</h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Every hourly check, including the ones where nothing needed changing.
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>
        <div className="divide-y divide-gray-100">
          {loading ? (
            <p className="p-5 text-sm text-gray-400 text-center">Loading…</p>
          ) : runs.length === 0 ? (
            <p className="p-5 text-sm text-gray-400 text-center">
              Nothing yet. Runs appear once the schedule is active, or when you
              use &quot;What would it do now?&quot;.
            </p>
          ) : runs.map(r => (
            <div key={r.id} className="px-5 py-3">
              <div className="flex items-center justify-between gap-2">
                <span className={`text-xs px-2 py-0.5 rounded font-medium ${OUTCOME_STYLE[r.outcome] ?? 'bg-gray-100 text-gray-600'}`}>
                  {outcomeLabel(r.outcome)}
                </span>
                <span className="text-xs text-gray-400">{r.local_time ?? new Date(r.ran_at).toLocaleString()}</span>
              </div>
              {r.desired_state && (
                <p className="text-xs text-gray-700 mt-1.5">
                  wanted <span className="font-medium">{r.desired_state}</span>
                  {r.previous_state && <> · was <span className="font-medium">{r.previous_state}</span></>}
                </p>
              )}
              {r.detail && <p className="text-xs text-gray-500 mt-1">{r.detail}</p>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

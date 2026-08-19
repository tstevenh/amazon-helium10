'use client'
/**
 * Keyword Intelligence (spec Part 17).
 *
 * Your own keyword history, built from exports you upload — not from a rank
 * scraper, which Decision 2 formally cancelled. Import is manual by design:
 * nothing here ever fetches from Helium 10 or Amazon on a schedule.
 *
 * The import is two steps because a one-shot upload would silently accept a
 * file whose column headers had changed, and the mistake would surface weeks
 * later as a flat trend line. Step 1 shows what was understood; step 2 commits.
 */
import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { api, ApiError } from '@/lib/api'
import type {
  KiStats, KiSnapshot, KiInspectResult, KiKeywordHit, KiTrendPoint,
  OpportunityBundle, CompareResult,
} from '@/lib/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/ui/LoadingState'
import { ErrorState } from '@/components/ui/ErrorState'

type Tab = 'import' | 'history' | 'trends' | 'opportunities' | 'compare'

export default function KeywordIntelPage() {
  const { user, loading: authLoading } = useAuth()
  const router = useRouter()

  const [tab, setTab] = useState<Tab>('trends')
  const [stats, setStats] = useState<KiStats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    if (!authLoading && !user) router.push('/login')
  }, [authLoading, user, router])

  const loadStats = useCallback(async () => {
    try {
      const s = await api.kiStats()
      setStats(s)
      // Nothing imported yet? The only useful tab is Import.
      if (s.snapshots === 0) setTab('import')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to load')
    }
  }, [])

  useEffect(() => { if (user) loadStats() }, [user, loadStats])

  function notify(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(null), 6000)
  }

  if (authLoading) return <LoadingState message="Loading…" />
  if (!user) return null
  if (error) return <ErrorState message={error} onRetry={loadStats} />

  const monthsOfHistory = stats?.first_date && stats?.last_date
    ? Math.round(
        (new Date(stats.last_date).getTime() - new Date(stats.first_date).getTime())
        / (1000 * 60 * 60 * 24 * 30),
      )
    : 0

  return (
    <div className="space-y-4">
      <PageHeader
        title="Keyword Intelligence"
        subtitle="Your own keyword history, built from exports you upload"
      />

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: 'Snapshots', value: stats.snapshots.toLocaleString() },
            { label: 'Keywords tracked', value: stats.keywords.toLocaleString() },
            { label: 'ASINs covered', value: stats.asins.toLocaleString() },
            { label: 'History span', value: monthsOfHistory > 0 ? `${monthsOfHistory} mo` : '—' },
          ].map(s => (
            <div key={s.label} className="rounded-xl border border-gray-200 bg-white p-4">
              <p className="text-xs text-gray-500">{s.label}</p>
              <p className="text-xl font-bold text-gray-900 mt-1">{s.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* The spec's own advice, stated where it matters rather than buried. */}
      {stats !== null && stats.snapshots < 3 && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
          <span className="font-medium">
            {stats.snapshots === 0 ? 'Nothing imported yet.' : `${stats.snapshots} snapshot${stats.snapshots === 1 ? '' : 's'} so far.`}
          </span>{' '}
          Trends need at least three snapshots per ASIN to say anything useful, and
          your own spec recommends keeping the Helium 10 subscription until this has
          3–6 months of history. Upload a Cerebro export whenever you take one.
        </div>
      )}

      {toast && (
        <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-2 text-sm text-green-700">✓ {toast}</div>
      )}

      <div className="flex gap-1 border-b border-gray-200">
        {([['trends', 'Keyword Trends'], ['opportunities', 'Opportunities'],
           ['compare', 'Compare Competitor'],
           ['import', 'Import Snapshot'], ['history', 'Snapshot History']] as const)
          .map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key as Tab)}
              className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
                tab === key
                  ? 'border-blue-600 text-blue-700'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {label}
            </button>
          ))}
      </div>

      {tab === 'import' && <ImportPanel onImported={m => { notify(m); loadStats(); setTab('history') }} />}
      {tab === 'history' && <HistoryPanel onChanged={loadStats} notify={notify} />}
      {tab === 'trends' && <TrendsPanel />}
      {tab === 'opportunities' && <OpportunitiesPanel />}
      {tab === 'compare' && <ComparePanel />}
    </div>
  )
}

// ── Import ────────────────────────────────────────────────────────────────

function ImportPanel({ onImported }: { onImported: (msg: string) => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [inspection, setInspection] = useState<KiInspectResult | null>(null)
  const [snapshotDate, setSnapshotDate] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function inspect(f: File) {
    setBusy(true); setErr(null); setInspection(null)
    try {
      const result = await api.kiInspect(f)
      setInspection(result)
      // Guess the date from the filename — exports are usually named for the
      // day they were taken, and the operator can correct it.
      const m = f.name.match(/(\d{4})[-_]?(\d{2})[-_]?(\d{2})/)
      setSnapshotDate(m ? `${m[1]}-${m[2]}-${m[3]}` : new Date().toISOString().slice(0, 10))
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not read that file')
    } finally {
      setBusy(false)
    }
  }

  async function commit() {
    if (!file || !inspection) return
    setBusy(true); setErr(null)
    try {
      const res = await api.kiImport(file, snapshotDate, inspection.detected_asins)
      onImported(`Imported ${res.row_count.toLocaleString()} rows dated ${res.snapshot_date}`)
      setFile(null); setInspection(null)
      if (fileRef.current) fileRef.current.value = ''
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Import failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card space-y-4">
      <div>
        <h2 className="font-semibold text-gray-900">Import a Cerebro export</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          In Helium 10, run Cerebro for your ASINs and export the CSV. Nothing is
          fetched automatically — you upload on whatever schedule suits you.
        </p>
      </div>

      <input
        ref={fileRef}
        type="file"
        accept=".csv,text/csv"
        onChange={e => {
          const f = e.target.files?.[0] ?? null
          setFile(f)
          if (f) inspect(f)
        }}
        className="block w-full text-sm border border-gray-300 rounded-lg p-2"
      />

      {busy && <p className="text-sm text-gray-400">Reading file…</p>}
      {err && <div className="bg-red-50 border border-red-200 rounded px-3 py-2 text-sm text-red-700">{err}</div>}

      {inspection && (
        <div className="space-y-3 border-t border-gray-100 pt-4">
          {inspection.warnings.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded px-3 py-2 text-sm text-red-700">
              {inspection.warnings.map((w, i) => <p key={i}>{w}</p>)}
            </div>
          )}

          {inspection.duplicate_of && (
            <div className="bg-yellow-50 border border-yellow-200 rounded px-3 py-2 text-sm text-yellow-900">
              <span className="font-medium">This exact file was already imported</span>{' '}
              on {new Date(inspection.duplicate_of.uploaded_at).toLocaleDateString()},
              dated {inspection.duplicate_of.snapshot_date}. Importing again will add a
              second copy — usually you do not want that.
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-sm">
            <div>
              <p className="text-xs text-gray-500">Rows found</p>
              <p className="font-semibold text-gray-900">{inspection.row_count.toLocaleString()}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">ASINs detected</p>
              <p className="font-semibold text-gray-900">
                {inspection.detected_asins.length ? inspection.detected_asins.join(', ') : 'none'}
              </p>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">
                Snapshot date <span className="text-red-500">*</span>
              </label>
              <input
                type="date"
                value={snapshotDate}
                onChange={e => setSnapshotDate(e.target.value)}
                className="input w-full text-sm py-1"
              />
              <p className="text-[11px] text-gray-400 mt-0.5">
                What the data represents, not today.
              </p>
            </div>
          </div>

          {/* Showing this is the whole point of the inspect step: a renamed
              Helium 10 column shows up here, not in a flat chart weeks later. */}
          <details className="text-sm">
            <summary className="cursor-pointer text-gray-600 hover:text-gray-800">
              Columns understood: {Object.keys(inspection.recognised_columns).length}
              {inspection.ignored_columns.length > 0 && ` · ignored: ${inspection.ignored_columns.length}`}
            </summary>
            <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <p className="text-xs font-medium text-gray-700 mb-1">Recognised</p>
                <ul className="text-xs text-gray-600 space-y-0.5">
                  {Object.entries(inspection.recognised_columns).map(([field, header]) => (
                    <li key={field}><span className="font-mono">{header}</span> → {field}</li>
                  ))}
                </ul>
              </div>
              {inspection.ignored_columns.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-700 mb-1">Ignored (still stored)</p>
                  <ul className="text-xs text-gray-500 space-y-0.5">
                    {inspection.ignored_columns.map(c => <li key={c} className="font-mono">{c}</li>)}
                  </ul>
                  <p className="text-[11px] text-gray-400 mt-1">
                    Every original column is kept, so nothing is lost — these just
                    aren&apos;t charted.
                  </p>
                </div>
              )}
            </div>
          </details>

          <button
            onClick={commit}
            disabled={busy || inspection.row_count === 0 || !snapshotDate}
            className="btn-primary disabled:opacity-50"
          >
            {busy ? 'Importing…' : `Import ${inspection.row_count.toLocaleString()} rows`}
          </button>
        </div>
      )}
    </div>
  )
}


/**
 * One snapshot's keyword rows.
 *
 * The endpoint behind this existed from the first version and nothing ever
 * called it, so Snapshot History listed imports without letting anyone open
 * one. Importing a second file then looked like it had overwritten the first,
 * when in fact the first was still stored and is what the trend patterns
 * compare against.
 */
function SnapshotDetail({
  snapshot, onBack,
}: { snapshot: KiSnapshot; onBack: () => void }) {
  const [rows, setRows] = useState<Record<string, unknown>[] | null>(null)
  const [search, setSearch] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Debounced so typing does not fire a request per keystroke against a
  // snapshot that can hold thousands of rows.
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    const t = setTimeout(() => {
      api.kiSnapshotKeywords(snapshot.id, { search: search.trim() || undefined, limit: 2000 })
        .then(r => { if (!cancelled) { setRows(r); setErr(null) } })
        .catch(e => { if (!cancelled) setErr(e instanceof ApiError ? e.message : 'Failed to load') })
        .finally(() => { if (!cancelled) setLoading(false) })
    }, 300)
    return () => { cancelled = true; clearTimeout(t) }
  }, [snapshot.id, search])

  return (
    <div className="card">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <button onClick={onBack} className="text-sm text-blue-600 hover:underline">
            ← Back to history
          </button>
          <h3 className="font-semibold text-gray-900 mt-1">
            Snapshot dated {snapshot.snapshot_date}
          </h3>
          <p className="text-xs text-gray-500 mt-0.5">
            {snapshot.row_count.toLocaleString()} rows
            {snapshot.asins.length > 0 && <> · {snapshot.asins.join(', ')}</>}
            {snapshot.original_filename && <> · {snapshot.original_filename}</>}
          </p>
        </div>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search keywords…"
          className="input text-sm w-56"
        />
      </div>

      {err ? (
        <p className="text-sm text-red-600 py-6 text-center">{err}</p>
      ) : loading && rows === null ? (
        <p className="text-sm text-gray-400 py-6 text-center">Loading…</p>
      ) : (rows ?? []).length === 0 ? (
        <p className="text-sm text-gray-400 py-6 text-center">
          {search ? `No keyword in this snapshot matches “${search}”.`
                  : 'This snapshot has no rows.'}
        </p>
      ) : (
        <ExportableTable rows={rows!} />
      )}
    </div>
  )
}

// ── History ───────────────────────────────────────────────────────────────

function HistoryPanel({
  onChanged, notify,
}: { onChanged: () => void; notify: (m: string) => void }) {
  const [rows, setRows] = useState<KiSnapshot[]>([])
  // Which snapshot is open, if any. History used to be a receipt list: you
  // could see that a March file had been imported and never look inside it,
  // so importing April felt like it had replaced March.
  const [open, setOpen] = useState<KiSnapshot | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try { setRows(await api.kiSnapshots()) } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  async function remove(s: KiSnapshot) {
    if (!window.confirm(
      `Delete the snapshot dated ${s.snapshot_date} (${s.row_count.toLocaleString()} rows)?\n\n` +
      `Its data disappears from every trend. This cannot be undone.`,
    )) return
    await api.kiDeleteSnapshot(s.id)
    notify(`Snapshot ${s.snapshot_date} deleted`)
    load(); onChanged()
  }

  if (loading) return <div className="card text-center py-12 text-gray-400">Loading…</div>
  if (open) return <SnapshotDetail snapshot={open} onBack={() => setOpen(null)} />
  if (rows.length === 0) {
    return <div className="card text-center py-12 text-gray-400">No snapshots imported yet.</div>
  }

  return (
    <div className="card p-0 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 bg-gray-50">
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Snapshot date</th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Source</th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">ASINs</th>
            <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600">Rows</th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Uploaded</th>
            <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600">Status</th>
            <th className="px-4 py-3 text-right text-xs font-semibold text-gray-600"></th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {rows.map(s => (
            <tr key={s.id} className="hover:bg-gray-50">
              <td className="px-4 py-3 font-medium text-gray-900">{s.snapshot_date}</td>
              <td className="px-4 py-3 text-gray-600 text-xs font-mono">{s.source_type}</td>
              <td className="px-4 py-3 text-gray-600 text-xs">{s.asins.join(', ') || '—'}</td>
              <td className="px-4 py-3 text-right text-gray-800">{s.row_count.toLocaleString()}</td>
              <td className="px-4 py-3 text-gray-500 text-xs">
                {new Date(s.uploaded_at).toLocaleDateString()}
                {s.uploaded_by_name && <> by {s.uploaded_by_name}</>}
                {s.original_filename && (
                  <div className="text-gray-400 truncate max-w-[180px]" title={s.original_filename}>
                    {s.original_filename}
                  </div>
                )}
              </td>
              <td className="px-4 py-3">
                <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                  s.status === 'completed' ? 'bg-green-100 text-green-700'
                    : s.status === 'failed' ? 'bg-red-100 text-red-700'
                    : 'bg-yellow-100 text-yellow-800'
                }`}>{s.status}</span>
                {s.error_message && (
                  <p className="text-xs text-red-600 mt-1 max-w-[220px]">{s.error_message}</p>
                )}
              </td>
              <td className="px-4 py-3 text-right whitespace-nowrap">
                <button onClick={() => setOpen(s)}
                        disabled={s.status !== 'completed'}
                        className="text-xs px-2 py-1 mr-1 bg-white border border-gray-300 text-gray-700 rounded hover:bg-gray-50 disabled:opacity-40"
                        title={s.status !== 'completed'
                          ? 'This import did not complete, so it has no rows to show'
                          : 'Open the keywords in this snapshot'}>
                  View data
                </button>
                <button onClick={() => remove(s)}
                        className="text-xs px-2 py-1 bg-white border border-red-200 text-red-500 rounded hover:bg-red-50">
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Trends ────────────────────────────────────────────────────────────────

function TrendsPanel() {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<KiKeywordHit[]>([])
  const [selected, setSelected] = useState<KiKeywordHit | null>(null)
  const [asin, setAsin] = useState<string>('')
  const [points, setPoints] = useState<KiTrendPoint[]>([])
  const [searching, setSearching] = useState(false)

  async function search(e: React.FormEvent) {
    e.preventDefault()
    if (!q.trim()) return
    setSearching(true)
    try { setHits(await api.kiSearchKeywords(q)) } finally { setSearching(false) }
  }

  const loadTrend = useCallback(async (hit: KiKeywordHit, a: string) => {
    setSelected(hit)
    setPoints(await api.kiKeywordTrend(hit.id, a || undefined))
  }, [])

  const asins = useMemo(
    () => Array.from(new Set(points.map(p => p.asin).filter(Boolean))) as string[],
    [points],
  )

  return (
    <div className="space-y-4">
      <form onSubmit={search} className="card flex gap-2">
        <input
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search an imported keyword…"
          className="input flex-1"
        />
        <button type="submit" className="btn-primary" disabled={searching}>
          {searching ? 'Searching…' : 'Search'}
        </button>
      </form>

      {hits.length > 0 && (
        <div className="card p-0 divide-y divide-gray-100 max-h-56 overflow-y-auto">
          {hits.map(h => (
            <button
              key={h.id}
              onClick={() => { setAsin(''); loadTrend(h, '') }}
              className={`w-full text-left px-4 py-2.5 hover:bg-gray-50 flex items-center gap-3 ${
                selected?.id === h.id ? 'bg-blue-50/50' : ''
              }`}
            >
              <span className="text-sm text-gray-900 flex-1 truncate">{h.keyword_text}</span>
              <span className="text-xs text-gray-500">
                {h.latest_search_volume?.toLocaleString() ?? '—'} vol
              </span>
              <span className="text-xs text-gray-400">
                {h.snapshot_count} snapshot{h.snapshot_count === 1 ? '' : 's'}
              </span>
            </button>
          ))}
        </div>
      )}

      {selected && (
        <div className="card">
          <div className="flex items-start justify-between flex-wrap gap-2 mb-3">
            <div>
              <h3 className="font-semibold text-gray-900">{selected.keyword_text}</h3>
              <p className="text-xs text-gray-500">
                {points.length} data point{points.length === 1 ? '' : 's'}
                {points.length < 3 && ' — trends need at least 3 to be meaningful'}
              </p>
            </div>
            {asins.length > 1 && (
              <select
                value={asin}
                onChange={e => { setAsin(e.target.value); loadTrend(selected, e.target.value) }}
                className="input text-sm py-1"
              >
                <option value="">All ASINs</option>
                {asins.map(a => <option key={a} value={a}>{a}</option>)}
              </select>
            )}
          </div>

          {points.length === 0 ? (
            <p className="text-sm text-gray-400 py-6 text-center">No data for this selection.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-600">Date</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-600">ASIN</th>
                    <th className="px-3 py-2 text-right text-xs font-semibold text-gray-600">Search volume</th>
                    <th className="px-3 py-2 text-right text-xs font-semibold text-gray-600">Organic rank</th>
                    <th className="px-3 py-2 text-right text-xs font-semibold text-gray-600">Sponsored rank</th>
                    <th className="px-3 py-2 text-right text-xs font-semibold text-gray-600">Competitors</th>
                    <th className="px-3 py-2 text-right text-xs font-semibold text-gray-600">CPC</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {points.map((p, i) => {
                    const prev = i > 0 ? points[i - 1] : null
                    // Rank is inverted: a smaller number is better, so an
                    // improvement shows green even though the value went down.
                    const rankDelta = prev && p.organic_rank != null && prev.organic_rank != null
                      ? prev.organic_rank - p.organic_rank : null
                    return (
                      <tr key={p.snapshot_date + (p.asin ?? '')}>
                        <td className="px-3 py-2 text-gray-800">{p.snapshot_date}</td>
                        <td className="px-3 py-2 text-gray-500 text-xs font-mono">{p.asin ?? '—'}</td>
                        <td className="px-3 py-2 text-right text-gray-800">
                          {p.search_volume?.toLocaleString() ?? '—'}
                        </td>
                        <td className="px-3 py-2 text-right">
                          <span className="text-gray-800">{p.organic_rank ?? '—'}</span>
                          {rankDelta !== null && rankDelta !== 0 && (
                            <span className={`ml-1 text-xs ${rankDelta > 0 ? 'text-green-600' : 'text-red-600'}`}>
                              {rankDelta > 0 ? `▲${rankDelta}` : `▼${Math.abs(rankDelta)}`}
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right text-gray-600">{p.sponsored_rank ?? '—'}</td>
                        <td className="px-3 py-2 text-right text-gray-600">
                          {p.competing_products_count?.toLocaleString() ?? '—'}
                        </td>
                        <td className="px-3 py-2 text-right text-gray-600">
                          {p.cpc != null ? `$${Number(p.cpc).toFixed(2)}` : '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}


// ── Opportunities (Phase 3) ───────────────────────────────────────────────

/**
 * The spec's five patterns (§17.5). Three need at least three snapshots to
 * mean anything; two work from one. That distinction is shown rather than
 * hidden, because an empty list with no explanation reads as a broken screen.
 */
/**
 * A paginated, selectable, exportable table over rows of unknown shape.
 *
 * Used by the Opportunities sections and by Snapshot History, which is why
 * it takes Record<string, unknown>[] and derives its columns: the two have
 * different shapes and both want the same copy/export behaviour.
 *
 * Previously these rendered `rows.slice(0, 25)` while the header displayed
 * `rows.length`, so a section announced "50 found" and showed 25 with no way
 * to reach the rest. And there was no way to get the data out at all, which
 * makes the whole screen read-only in the least useful sense — a PPC manager
 * wants these keywords in a bulk upload sheet, not on screen.
 */
function ExportableTable({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = useMemo(
    () => Object.keys(rows[0] ?? {}).filter(k => k !== 'keyword_id'),
    [rows],
  )
  // A stable identity per row. keyword_id when the pattern provides one,
  // otherwise the index — selection must survive a page change.
  const idOf = (r: Record<string, unknown>, i: number) =>
    (r.keyword_id as string) ?? `idx-${i}`

  const [pageSize, setPageSize] = useState(25)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [copied, setCopied] = useState<string | null>(null)

  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize))
  const shown = rows.slice((page - 1) * pageSize, page * pageSize)
  const allSelected = rows.length > 0 && selected.size === rows.length

  function toggle(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(rows.map(idOf)))
  }

  /** Tab-separated, so a paste lands in separate columns in Excel or Sheets. */
  function asTsv(subset: Record<string, unknown>[]) {
    const head = columns.join('\t')
    const body = subset.map(r =>
      columns.map(c => (r[c] == null ? '' : String(r[c]))).join('\t'),
    )
    return [head, ...body].join('\n')
  }

  async function copy(subset: Record<string, unknown>[], label: string) {
    const text = asTsv(subset)
    try {
      await navigator.clipboard.writeText(text)
    } catch {
      // clipboard API needs a secure context and permission; fall back rather
      // than failing silently, which would look like a broken button.
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
    }
    setCopied(`${label} (${subset.length} rows)`)
    setTimeout(() => setCopied(null), 2500)
  }

  function exportCsv(subset: Record<string, unknown>[]) {
    // Quote every field: keyword text legitimately contains commas.
    const esc = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`
    const csv = [
      columns.map(esc).join(','),
      ...subset.map(r => columns.map(c => esc(r[c])).join(',')),
    ].join('\n')
    // BOM so Excel opens UTF-8 keyword text correctly instead of mojibake.
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `opportunities-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const selectedRows = rows.filter((r, i) => selected.has(idOf(r, i)))

  return (
    <div className="mt-3">
      <div className="flex items-center gap-2 flex-wrap text-xs mb-2">
        <span className="text-gray-500">
          {selected.size > 0 ? `${selected.size} selected` : `${rows.length} rows`}
        </span>
        <button type="button" className="btn-secondary text-xs py-1 px-2"
                disabled={selected.size === 0}
                onClick={() => copy(selectedRows, 'Copied selected')}>
          Copy selected
        </button>
        <button type="button" className="btn-secondary text-xs py-1 px-2"
                onClick={() => copy(rows, 'Copied all')}>
          Copy all
        </button>
        <button type="button" className="btn-secondary text-xs py-1 px-2"
                onClick={() => exportCsv(selected.size > 0 ? selectedRows : rows)}>
          Export CSV{selected.size > 0 ? ' (selected)' : ''}
        </button>
        <span className="ml-auto flex items-center gap-1 text-gray-500">
          Rows
          <select
            className="input text-xs py-0.5 px-1"
            value={pageSize}
            onChange={e => { setPageSize(Number(e.target.value)); setPage(1) }}
          >
            {[25, 50, 100, 500].map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </span>
      </div>

      {copied && <p className="text-xs text-green-700 mb-2">{copied} — paste into Excel or Sheets.</p>}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th className="px-2 py-2 w-8">
                <input type="checkbox" checked={allSelected} onChange={toggleAll}
                       aria-label="Select all rows" />
              </th>
              {columns.map(k => (
                <th key={k} className="px-3 py-2 text-left text-xs font-semibold text-gray-600">
                  {k.replace(/_/g, ' ')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {shown.map((r, i) => {
              const id = idOf(r, (page - 1) * pageSize + i)
              return (
                <tr key={id} className="hover:bg-gray-50">
                  <td className="px-2 py-2">
                    <input type="checkbox" checked={selected.has(id)}
                           onChange={() => toggle(id)} aria-label="Select row" />
                  </td>
                  {columns.map(k => (
                    <td key={k} className="px-3 py-2 text-gray-800">
                      {r[k] == null ? '—' : String(r[k])}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-2 text-xs text-gray-500">
          <span>
            Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, rows.length)} of {rows.length}
          </span>
          <span className="flex items-center gap-1">
            <button type="button" className="btn-secondary text-xs py-1 px-2"
                    disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
              Prev
            </button>
            <span>{page} / {totalPages}</span>
            <button type="button" className="btn-secondary text-xs py-1 px-2"
                    disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
              Next
            </button>
          </span>
        </div>
      )}
    </div>
  )
}

function OpportunitiesPanel() {
  const [data, setData]       = useState<OpportunityBundle | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr]         = useState<string | null>(null)

  useEffect(() => {
    api.kiOpportunities()
      .then(setData)
      .catch(e => setErr(e instanceof ApiError ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="card text-center py-12 text-gray-400">Loading…</div>
  if (err) return <div className="card text-center py-12 text-red-600">{err}</div>
  if (!data) return null

  const needed = data.min_snapshots_for_trends
  const counts = Object.entries(data.snapshot_counts_by_asin)

  const sections: { key: keyof OpportunityBundle; title: string; blurb: string; trend: boolean }[] = [
    { key: 'missing_from_ppc', trend: false,
      title: 'Keywords you are not bidding on',
      blurb: 'Healthy search volume in your imported data, with no matching keyword in any campaign.' },
    { key: 'missing_from_listings', trend: false,
      title: 'Keywords missing from your listing copy',
      blurb: 'Not found in the title, bullets or backend keywords you have entered for that ASIN.' },
    { key: 'volume_increasing', trend: true,
      title: 'Search volume climbing',
      blurb: 'Comparing your first and latest snapshot, not Amazon’s own trend column.' },
    { key: 'rank_declining', trend: true,
      title: 'Slipping organically',
      blurb: 'Your organic position got worse between the last two snapshots.' },
    { key: 'competition_increasing', trend: true,
      title: 'Getting more crowded',
      blurb: 'More competing products than last snapshot — a defensive bid candidate.' },
  ]

  return (
    <div className="space-y-4">
      {!data.trends_available && (
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
          <span className="font-medium">
            Trend-based opportunities need {needed} snapshots of the same ASIN,
            taken on {needed} different dates.
          </span>{' '}
          {counts.length === 0
            ? 'Nothing has been imported yet'
            : counts.map(([asin, n]) => `${asin}: ${n}`).join(' · ')}
          . The first two sections below work from a single snapshot, so they are
          useful straight away.
        </div>
      )}

      <p className="text-xs text-gray-500">
        These use the <strong>newest value you have imported</strong> for each
        keyword, not the last file you uploaded — so figures change when you import
        a more recent snapshot, which is the point. Older snapshots are not
        replaced: they stay in <strong>Snapshot History</strong>, where you can open
        and export any of them, and the trend sections below compare them.
      </p>

      {sections.map(sec => {
        const rows = (data[sec.key] as Record<string, unknown>[]) ?? []
        const blocked = sec.trend && !data.trends_available
        return (
          <div key={String(sec.key)} className="card">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <h3 className="font-semibold text-gray-900 text-sm">{sec.title}</h3>
                <p className="text-xs text-gray-500 mt-0.5">{sec.blurb}</p>
              </div>
              <span className="text-xs text-gray-400 shrink-0">
                {blocked
                  ? `needs ${needed} dates for one ASIN`
                  : `${rows.length} found`}
              </span>
            </div>

            {blocked ? (
              // "needs 3 snapshots" was read as "upload 3 ASINs", which
              // produces one snapshot each and never unlocks anything. Say
              // what is actually required: the SAME ASIN at three different
              // snapshot dates.
              <div className="text-sm text-gray-400 py-4 text-center space-y-1">
                <p>Not enough history yet — this is not an error.</p>
                <p className="text-xs">
                  These three need the <strong>same ASIN</strong> imported at{' '}
                  {needed} <strong>different snapshot dates</strong> (e.g. one
                  Cerebro export for March, one for April, one for May), so there
                  is a before and after to compare. {needed} different ASINs from
                  the same week gives one date each and unlocks nothing.
                </p>
                <p className="text-xs">
                  The date comes from the <em>Snapshot date</em> field you set when
                  importing, not from when you uploaded the file — so you can
                  import all three today.
                </p>
              </div>
            ) : rows.length === 0 ? (
              <p className="text-sm text-gray-400 py-4 text-center">
                Nothing matched. That is a good result for this one.
              </p>
            ) : (
              <ExportableTable rows={rows} />
            )}
          </div>
        )
      })}
    </div>
  )
}


// ── Competitor comparison (Phase 3) ───────────────────────────────────────

/**
 * Keyword gap against one competitor ASIN.
 *
 * The catch worth stating up front: this compares two ASINs using data YOU
 * imported, so it needs a Cerebro export run against the competitor's ASIN —
 * not yours. Without that, there is nothing to compare and the screen would
 * look broken rather than under-supplied.
 */
function ComparePanel() {
  const [mine, setMine] = useState('')
  const [theirs, setTheirs] = useState('')
  const [known, setKnown] = useState<string[]>([])
  const [result, setResult] = useState<CompareResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  // Offer the ASINs actually present in imported snapshots, so nobody types an
  // ASIN we have no data for and reads the empty result as a bug.
  useEffect(() => {
    api.kiOpportunities()
      .then(d => setKnown(Object.keys(d.snapshot_counts_by_asin)))
      .catch(() => setKnown([]))
  }, [])

  async function run(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setErr(null); setResult(null)
    try {
      setResult(await api.kiCompare(mine.trim(), theirs.trim()))
    } catch (e2) {
      setErr(e2 instanceof ApiError ? e2.message : 'Comparison failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="card">
        <h2 className="font-semibold text-gray-900 text-sm">Compare against a competitor</h2>
        <p className="text-xs text-gray-500 mt-0.5 mb-3">
          Finds keywords where they rank and you do not, or where they outrank you.
          Needs a Cerebro export covering <span className="font-medium">their</span> ASIN —
          run Cerebro against their listing, then import it.
        </p>

        <form onSubmit={run} className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Your ASIN</label>
            <input
              value={mine}
              onChange={e => setMine(e.target.value.toUpperCase())}
              placeholder="B0XXXXXXXX"
              className="input w-full font-mono text-sm"
              required
              minLength={8}
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Competitor ASIN</label>
            <input
              value={theirs}
              onChange={e => setTheirs(e.target.value.toUpperCase())}
              placeholder="B0YYYYYYYY"
              className="input w-full font-mono text-sm"
              required
              minLength={8}
            />
          </div>
          <button type="submit" className="btn-primary" disabled={busy}>
            {busy ? 'Comparing…' : 'Compare'}
          </button>
        </form>

        {known.length > 0 && (
          <p className="text-xs text-gray-400 mt-2">
            ASINs you have imported data for: {known.join(', ')}
          </p>
        )}
        {known.length === 0 && (
          <p className="text-xs text-yellow-700 mt-2">
            No snapshots imported yet, so any comparison will come back empty.
          </p>
        )}
      </div>

      {err && (
        <div className="card text-sm text-red-700">{err}</div>
      )}

      {result && (
        <div className="card">
          <div className="flex items-center gap-4 flex-wrap mb-3">
            <div>
              <p className="text-xs text-gray-500">You are invisible for</p>
              <p className="text-2xl font-bold text-red-600">{result.not_ranking}</p>
              <p className="text-xs text-gray-400">keywords they rank for</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">They outrank you on</p>
              <p className="text-2xl font-bold text-yellow-700">{result.outranked}</p>
              <p className="text-xs text-gray-400">keywords you both rank for</p>
            </div>
            <p className="text-xs text-gray-400 ml-auto font-mono">
              {result.my_asin} vs {result.competitor_asin}
            </p>
          </div>

          {result.gaps.length === 0 ? (
            <p className="text-sm text-gray-400 py-6 text-center">
              No gaps found. Either you are ahead everywhere, or there is no
              imported snapshot covering {result.competitor_asin}.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-600">Keyword</th>
                    <th className="px-3 py-2 text-right text-xs font-semibold text-gray-600">Search volume</th>
                    <th className="px-3 py-2 text-right text-xs font-semibold text-gray-600">Your rank</th>
                    <th className="px-3 py-2 text-right text-xs font-semibold text-gray-600">Their rank</th>
                    <th className="px-3 py-2 text-left text-xs font-semibold text-gray-600">Gap</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {result.gaps.slice(0, 100).map(g => (
                    <tr key={g.keyword_id} className="hover:bg-gray-50">
                      <td className="px-3 py-2 text-gray-900">{g.keyword_text}</td>
                      <td className="px-3 py-2 text-right text-gray-700">
                        {g.search_volume?.toLocaleString() ?? '—'}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {g.my_rank == null
                          ? <span className="text-red-600">not ranking</span>
                          : <span className="text-gray-800">{g.my_rank}</span>}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-800">{g.competitor_rank}</td>
                      <td className="px-3 py-2">
                        <span className={`text-xs px-2 py-0.5 rounded font-medium ${
                          g.gap_type === 'not_ranking'
                            ? 'bg-red-100 text-red-700'
                            : 'bg-yellow-100 text-yellow-800'
                        }`}>
                          {g.gap_type === 'not_ranking' ? 'invisible' : 'outranked'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {result.gaps.length > 100 && (
                <p className="text-xs text-gray-400 mt-2">
                  Showing 100 of {result.gaps.length}, highest search volume first.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

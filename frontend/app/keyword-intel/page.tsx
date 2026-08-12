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
} from '@/lib/types'
import { PageHeader } from '@/components/layout/PageHeader'
import { LoadingState } from '@/components/ui/LoadingState'
import { ErrorState } from '@/components/ui/ErrorState'

type Tab = 'import' | 'history' | 'trends'

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
        {([['trends', 'Keyword Trends'], ['import', 'Import Snapshot'], ['history', 'Snapshot History']] as const)
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

// ── History ───────────────────────────────────────────────────────────────

function HistoryPanel({
  onChanged, notify,
}: { onChanged: () => void; notify: (m: string) => void }) {
  const [rows, setRows] = useState<KiSnapshot[]>([])
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
              <td className="px-4 py-3 text-right">
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

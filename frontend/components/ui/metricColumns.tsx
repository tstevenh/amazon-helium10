/**
 * The performance columns shared by Campaigns, Ad Groups and Keywords.
 *
 * These lived only on the Campaigns page, so Ad Groups and Keywords listed
 * names and bids with no spend, sales or ACOS at all — you could see that a
 * keyword existed but not whether it was making or losing money. Defining
 * them once keeps the three screens reading the same way, so a number means
 * the same thing wherever the team looks at it.
 */
import { Column } from '@/components/ui/DataTable'
import type { PerfMetrics } from '@/lib/types'

export const fmt = {
  currency: (v: number | null | undefined) =>
    v == null ? '—' : `$${Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
  int:  (v: number | null | undefined) => v == null ? '—' : Number(v).toLocaleString('en-US'),
  pct:  (v: number | null | undefined) => v == null ? '—' : `${(Number(v) * 100).toFixed(2)}%`,
  acos: (v: number | null | undefined) => v == null ? '—' : `${Number(v).toFixed(1)}%`,
  roas: (v: number | null | undefined) => v == null ? '—' : Number(v).toFixed(2),
}

/**
 * Sort keys use sentinels rather than null so "no data" sinks to the bottom
 * in either direction: -1 for "more is better" metrics, 9999 for ACOS where
 * lower is better.
 */
export function metricColumns<T extends PerfMetrics>(): Column<T>[] {
  return [
    {
      header: 'Spend',
      cell: row => <span className={`text-sm ${row.spend != null ? 'text-gray-900 font-medium' : 'text-gray-400'}`}>{fmt.currency(row.spend)}</span>,
      sortValue: row => row.spend ?? -1,
    },
    {
      header: 'Sales',
      cell: row => <span className={`text-sm ${row.sales != null ? 'text-gray-900' : 'text-gray-400'}`}>{fmt.currency(row.sales)}</span>,
      sortValue: row => row.sales ?? -1,
    },
    {
      header: 'ACOS',
      cell: row => {
        const v = row.acos != null ? Number(row.acos) : null
        // Thresholds match the Campaigns page so the same colour means the
        // same thing on every screen.
        const color = v == null ? 'text-gray-400' : v > 40 ? 'text-red-600' : v > 25 ? 'text-yellow-700' : 'text-green-600'
        return <span className={`text-sm font-medium ${color}`}>{fmt.acos(row.acos)}</span>
      },
      sortValue: row => row.acos ?? 9999,
    },
    {
      header: 'ROAS',
      cell: row => <span className={`text-sm ${row.roas != null ? 'text-gray-900' : 'text-gray-400'}`}>{fmt.roas(row.roas)}</span>,
      sortValue: row => row.roas ?? -1,
    },
    {
      header: 'Orders',
      cell: row => <span className="text-sm text-gray-700">{fmt.int(row.orders)}</span>,
      sortValue: row => row.orders ?? -1,
    },
    {
      header: 'Clicks',
      cell: row => <span className="text-sm text-gray-700">{fmt.int(row.clicks)}</span>,
      sortValue: row => row.clicks ?? -1,
    },
    {
      header: 'Impr.',
      cell: row => <span className="text-sm text-gray-500">{fmt.int(row.impressions)}</span>,
      sortValue: row => row.impressions ?? -1,
    },
    {
      header: 'CPC',
      cell: row => <span className="text-sm text-gray-600">{fmt.currency(row.cpc)}</span>,
      sortValue: row => row.cpc ?? -1,
    },
    {
      header: 'CTR',
      cell: row => <span className="text-sm text-gray-500">{fmt.pct(row.ctr)}</span>,
      sortValue: row => row.ctr ?? -1,
    },
  ]
}

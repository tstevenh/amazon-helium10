import * as React from 'react'
import { cn } from '@/lib/cn'

/**
 * A row of totals above a table.
 *
 * This replaces six identical bordered cards, each with a small label and a
 * 20px bold number. That layout is the stat-card grid — a shape that reads as
 * dashboard decoration rather than information, and here it also spent about
 * 90px of vertical space above the table people actually work in.
 *
 * One bordered strip, values separated by hairlines. The numbers still dominate,
 * because they are larger and darker than their labels; they no longer each need
 * their own box to say so.
 *
 * `hint` carries the unit or period — a bare "19.6%" invites the reader to
 * supply their own meaning, and in an advertising tool the wrong guess is
 * expensive.
 */
export interface Stat {
  label: string
  value: React.ReactNode
  hint?: React.ReactNode
  /** Only for values whose direction is genuinely good or bad. Never decorative. */
  tone?: 'ok' | 'warn' | 'danger'
}

export function StatBar({
  stats, className,
}: { stats: Stat[]; className?: string }) {
  return (
    <div
      className={cn(
        'mb-4 flex flex-wrap items-stretch overflow-hidden rounded-lg',
        'border border-hairline bg-surface',
        className,
      )}
    >
      {stats.map((s, i) => (
        <div
          key={s.label}
          className={cn(
            'min-w-[8.5rem] flex-1 px-4 py-2.5',
            // A divider between, never around: a border on each item would
            // rebuild the card grid this exists to replace.
            i > 0 && 'border-l border-hairline',
          )}
        >
          <p className="text-xs text-ink-muted">{s.label}</p>
          <p className="mt-0.5 flex items-baseline gap-1.5">
            <span
              className={cn(
                'text-lg font-semibold tabular tracking-tight',
                s.tone === 'ok' && 'text-ok',
                s.tone === 'warn' && 'text-warn',
                s.tone === 'danger' && 'text-danger',
                !s.tone && 'text-ink',
              )}
            >
              {s.value}
            </span>
            {s.hint && <span className="text-xs text-ink-subtle">{s.hint}</span>}
          </p>
        </div>
      ))}
    </div>
  )
}

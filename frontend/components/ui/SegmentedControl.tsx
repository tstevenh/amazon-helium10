'use client'
import * as React from 'react'
import { cn } from '@/lib/cn'

/**
 * A small set of mutually exclusive choices — date presets, view modes.
 *
 * One bordered track with the selection lifted inside it, rather than four
 * separate buttons where the active one is filled. Separate buttons read as four
 * independent actions; a segmented control reads as one setting with four
 * positions, which is what a date range is.
 *
 * Radio semantics, not buttons, so arrow keys move between options and a screen
 * reader announces "2 of 4 selected".
 */
export function SegmentedControl<T extends string>({
  value, options, onChange, ariaLabel, className,
}: {
  value: T | null
  options: { value: T; label: React.ReactNode; title?: string }[]
  onChange: (value: T) => void
  ariaLabel: string
  className?: string
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn(
        'inline-flex items-center gap-0.5 rounded-md border border-line bg-surface-sunken p-0.5',
        className,
      )}
    >
      {options.map(opt => {
        const selected = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={selected}
            title={opt.title}
            onClick={() => onChange(opt.value)}
            className={cn(
              'rounded px-2.5 py-1 text-xs font-medium transition-colors duration-150 ease-out',
              selected
                // The selected segment is a raised white surface, not the accent
                // at full strength: this is a filter, not the primary action on
                // the screen, and it should not outrank the Sync button.
                ? 'bg-surface text-ink shadow-sm'
                : 'text-ink-muted hover:text-ink',
            )}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}

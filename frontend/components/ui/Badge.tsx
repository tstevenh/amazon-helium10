import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

/**
 * A small labelled state.
 *
 * Tinted background rather than a saturated fill: a table with twenty rows of
 * solid green pills is a table nobody can scan. And the text is always present —
 * this app gets screenshotted into WhatsApp threads, where a colour-only signal
 * survives neither the compression nor a colour-blind reader.
 */
const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-2xs font-medium whitespace-nowrap',
  {
    variants: {
      tone: {
        neutral: 'bg-surface-sunken text-ink-muted border border-hairline',
        ok:      'bg-ok-tint text-ok border border-ok/20',
        warn:    'bg-warn-tint text-warn border border-warn/20',
        danger:  'bg-danger-tint text-danger border border-danger/20',
        info:    'bg-info-tint text-info border border-info/20',
        accent:  'bg-accent-weak text-accent border border-accent-edge',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />
}
export { badgeVariants }

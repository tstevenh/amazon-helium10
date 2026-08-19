'use client'
import * as React from 'react'
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'
import { Button } from '@/components/ui/Button'

/**
 * An inline message: result of an action, a warning, a piece of context.
 *
 * One component for what used to be eight screens' worth of hand-rolled strips,
 * each a slightly different `bg-ok-tint border border-ok/20 …` with a
 * literal ✓ / ✗ / ⚠ / ✅ / ❌ typed into the string. Beyond the inconsistency,
 * those glyphs are emoji on most platforms: they render at a different weight
 * per OS, sit off the baseline, and cannot be styled.
 *
 * The icon is not decoration. This app gets screenshotted into WhatsApp threads
 * and read by people who may not distinguish red from green, so the shape has to
 * carry the meaning as well as the colour.
 */
const noticeVariants = cva(
  'flex items-start gap-2 rounded-lg border px-3 py-2 text-sm',
  {
    variants: {
      tone: {
        ok:     'border-ok/20 bg-ok-tint text-ok',
        danger: 'border-danger/20 bg-danger-tint text-danger',
        warn:   'border-warn/20 bg-warn-tint text-warn',
        info:   'border-info/20 bg-info-tint text-info',
        neutral:'border-hairline bg-surface-sunken text-ink-muted',
      },
    },
    defaultVariants: { tone: 'info' },
  },
)

const ICONS = {
  ok: CheckCircle2,
  danger: XCircle,
  warn: AlertTriangle,
  info: Info,
  neutral: Info,
} as const

export interface NoticeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof noticeVariants> {
  /** Renders a dismiss button. Omit for messages that should stay put. */
  onDismiss?: () => void
  /** Right-aligned action, e.g. Retry. */
  action?: React.ReactNode
}

export function Notice({
  className, tone, children, onDismiss, action, ...props
}: NoticeProps) {
  const Icon = ICONS[tone ?? 'info']
  return (
    <div
      // Assertive would interrupt a screen reader mid-sentence; these are
      // results and context, not emergencies.
      role="status"
      className={cn(noticeVariants({ tone }), className)}
      {...props}
    >
      <Icon size={15} className="mt-0.5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">{children}</div>
      {action}
      {onDismiss && (
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onDismiss}
          aria-label="Dismiss"
          // Inherits the notice's tone rather than reverting to grey, so the
          // control belongs to the message it closes.
          className="-mr-1 -mt-0.5 shrink-0 text-current hover:bg-black/5"
        >
          <X aria-hidden />
        </Button>
      )}
    </div>
  )
}

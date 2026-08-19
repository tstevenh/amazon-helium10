import * as React from 'react'
import { cn } from '@/lib/cn'

/**
 * A bordered surface.
 *
 * Deliberately thin: no shadow, no gradient, no icon slot. Cards are the lazy
 * answer to hierarchy and this codebase already nests them in three places —
 * which is always wrong. Reach for spacing and a heading first; use Card only
 * when a real boundary exists between two kinds of content.
 */
export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-lg border border-hairline bg-surface', className)}
      {...props}
    />
  )
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('flex flex-wrap items-start justify-between gap-3 px-4 py-3', className)}
      {...props}
    />
  )
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn('text-md font-semibold text-ink', className)} {...props} />
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  // ink-muted, not ink-faint: this is body copy and has to clear 4.5:1.
  return <p className={cn('text-xs text-ink-muted', className)} {...props} />
}

export function CardBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-4 pb-4', className)} {...props} />
}

/** A rule between card sections. Uses the hairline token, never a raw gray. */
export function CardSeparator({ className }: { className?: string }) {
  return <div className={cn('border-t border-hairline', className)} />
}

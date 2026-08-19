'use client'
import * as React from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Button } from '@/components/ui/Button'

/**
 * A right-hand detail panel.
 *
 * Built on Radix Dialog rather than a hand-rolled `fixed inset-0`, which is what
 * this replaced. The hand-rolled version listened for Escape and stopped there:
 * Tab walked straight out of the panel into the page behind it, focus never
 * returned to the row that opened it, the background stayed scrollable, and
 * nothing told a screen reader a dialog had opened. Radix supplies the focus
 * trap, focus restoration, scroll lock, and role="dialog" with an
 * aria-labelledby pointing at the title — verified in the browser. It hides the
 * rest of the page with aria-hidden and focus guards rather than setting
 * aria-modal; the effect is the same or stronger, but do not expect that
 * attribute if you go looking for it.
 *
 * A drawer, not a modal, because the reader is comparing the detail against the
 * table it came from; a centred modal would cover it.
 */
export function Drawer({
  open, onOpenChange, title, subtitle, children, footer, className,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: React.ReactNode
  subtitle?: React.ReactNode
  children: React.ReactNode
  footer?: React.ReactNode
  className?: string
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay
          className={cn(
            'fixed inset-0 z-overlay bg-ink/20',
            'data-[state=open]:animate-in data-[state=open]:fade-in-0',
            'data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
          )}
        />
        <Dialog.Content
          className={cn(
            'fixed right-0 top-0 z-modal flex h-full w-full max-w-md flex-col',
            'border-l border-hairline bg-surface shadow-md',
            // Slides in from the edge it belongs to. 200ms, ease-out — long
            // enough to read as a panel arriving, short enough not to wait for.
            'duration-200 ease-out',
            'data-[state=open]:animate-in data-[state=open]:slide-in-from-right',
            'data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right',
            className,
          )}
        >
          <div className="flex items-start justify-between gap-3 border-b border-hairline px-4 py-3">
            <div className="min-w-0">
              {subtitle && <p className="text-xs text-ink-subtle">{subtitle}</p>}
              <Dialog.Title className="break-words text-md font-semibold text-ink">
                {title}
              </Dialog.Title>
            </div>
            <Dialog.Close asChild>
              {/* A real button, not a bare × glyph: it needs a hit area, a hover
                  state and an accessible name. */}
              <Button variant="ghost" size="icon-sm" aria-label="Close panel">
                <X aria-hidden />
              </Button>
            </Dialog.Close>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>

          {footer && (
            <div className="border-t border-hairline bg-surface px-4 py-3">{footer}</div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

/** A labelled row inside a drawer. Used for the metric read-outs. */
export function DrawerRow({
  label, value, className,
}: { label: React.ReactNode; value: React.ReactNode; className?: string }) {
  return (
    <div className={cn('flex items-baseline justify-between gap-4 py-1.5', className)}>
      <span className="text-xs text-ink-muted">{label}</span>
      <span className="text-sm tabular text-ink">{value}</span>
    </div>
  )
}

/** A section heading inside a drawer. */
export function DrawerSection({
  title, children, className,
}: { title: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn('border-b border-hairline px-4 py-3 last:border-0', className)}>
      <h3 className="mb-1.5 text-xs font-medium text-ink-muted">{title}</h3>
      {children}
    </section>
  )
}

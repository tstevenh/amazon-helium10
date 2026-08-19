'use client'
import * as React from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { MoreHorizontal } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Button } from '@/components/ui/Button'

/**
 * An overflow menu for row actions.
 *
 * Exists because the Rules table carried five controls in every row — Run,
 * Clone, Edit, Enable/Disable, Delete — which wrapped onto two lines and made
 * fifteen buttons compete for attention across three rows. With Delete sitting a
 * few pixels from Enable.
 *
 * The pattern: keep the one action people came for, move the rest here. Nothing
 * is removed; the row just stops shouting.
 *
 * Radix handles the parts that are easy to get wrong by hand: it renders in a
 * portal so the menu is not clipped by the table's overflow-x-auto, closes on
 * outside click and Escape, moves focus with the arrow keys, and returns focus to
 * the trigger afterwards.
 */
export function RowMenu({
  children, label = 'More actions', align = 'end',
}: {
  children: React.ReactNode
  label?: string
  align?: 'start' | 'end'
}) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={label}>
          <MoreHorizontal aria-hidden />
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align={align}
          sideOffset={4}
          className={cn(
            'z-dropdown min-w-[9rem] overflow-hidden rounded-md border border-line',
            'bg-surface p-1 shadow-md',
            'data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95',
            'data-[state=closed]:animate-out data-[state=closed]:fade-out-0',
          )}
        >
          {children}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

export function MenuItem({
  className, danger, children, ...props
}: React.ComponentPropsWithoutRef<typeof DropdownMenu.Item> & { danger?: boolean }) {
  return (
    <DropdownMenu.Item
      className={cn(
        'flex cursor-pointer select-none items-center gap-2 rounded px-2 py-1.5 text-sm outline-none',
        'data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
        '[&_svg]:size-3.5 [&_svg]:shrink-0',
        danger
          // Destructive items read destructive before they are clicked, and sit
          // below a separator so a mis-aimed click lands on nothing.
          ? 'text-danger data-[highlighted]:bg-danger-tint'
          : 'text-ink data-[highlighted]:bg-surface-hover',
        className,
      )}
      {...props}
    >
      {children}
    </DropdownMenu.Item>
  )
}

export function MenuSeparator() {
  return <DropdownMenu.Separator className="-mx-1 my-1 h-px bg-hairline" />
}

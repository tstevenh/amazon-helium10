'use client'
import * as React from 'react'
import * as LabelPrimitive from '@radix-ui/react-label'
import { cn } from '@/lib/cn'

/**
 * Form controls.
 *
 * Radix Label rather than a bare <label> so clicking the text focuses the
 * control even when the markup between them changes shape — which it does in the
 * rule builder, where fields are generated.
 */
export const Label = React.forwardRef<
  React.ElementRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(({ className, ...props }, ref) => (
  <LabelPrimitive.Root
    ref={ref}
    className={cn(
      'block text-xs font-medium text-ink-muted',
      'peer-disabled:opacity-60',
      className,
    )}
    {...props}
  />
))
Label.displayName = 'Label'

const control = cn(
  'block w-full rounded-md border border-line bg-surface text-sm text-ink',
  'transition-colors duration-150 ease-out',
  'hover:border-line-strong',
  // Ring rather than a thicker border: a border change reflows the control by a
  // pixel and nudges everything beside it on every focus.
  'focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20',
  'disabled:opacity-50 disabled:cursor-not-allowed disabled:bg-surface-sunken',
  'aria-[invalid=true]:border-danger aria-[invalid=true]:ring-danger/20',
)

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input ref={ref} className={cn(control, 'h-8 px-2.5', className)} {...props} />
  ),
)
Input.displayName = 'Input'

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea ref={ref} className={cn(control, 'min-h-16 px-2.5 py-1.5', className)} {...props} />
))
Textarea.displayName = 'Textarea'

/**
 * A native <select>, styled.
 *
 * Not Radix Select. The marketplace picker and the rule-field pickers hold
 * hundreds of options, and native select gets type-ahead, virtualisation and the
 * platform's own mobile wheel for free — all of which a custom listbox would
 * have to reimplement worse. Radix is the right call for menus, not for this.
 */
export const Select = React.forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, ...props }, ref) => (
  <select
    ref={ref}
    className={cn(
      control,
      'h-8 cursor-pointer appearance-none bg-no-repeat pl-2.5 pr-7',
      // Inline chevron: one background-image beats shipping a wrapper div and an
      // absolutely-positioned icon on every select in the app.
      "bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20width%3D%2216%22%20height%3D%2216%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20stroke%3D%22%236b7280%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%3E%3Cpath%20d%3D%22m6%209%206%206%206-6%22/%3E%3C/svg%3E')]",
      'bg-[position:right_0.5rem_center] bg-[size:1rem]',
      className,
    )}
    {...props}
  />
))
Select.displayName = 'Select'

/** Label + control + optional hint/error, spaced consistently. */
export function FormField({
  label, hint, error, htmlFor, children, className,
}: {
  label?: React.ReactNode
  hint?: React.ReactNode
  error?: React.ReactNode
  htmlFor?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('space-y-1', className)}>
      {label && <Label htmlFor={htmlFor}>{label}</Label>}
      {children}
      {/* Error replaces hint rather than stacking: two lines of guidance under
          one field is how a form starts jumping as you fill it in. */}
      {error ? (
        <p className="text-xs text-danger">{error}</p>
      ) : hint ? (
        <p className="text-xs text-ink-subtle">{hint}</p>
      ) : null}
    </div>
  )
}

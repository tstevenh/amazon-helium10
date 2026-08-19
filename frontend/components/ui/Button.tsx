'use client'
import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/cn'

/**
 * One button vocabulary for the whole app.
 *
 * The old build had .btn-primary, .btn-secondary, and a dozen hand-rolled
 * `className="text-xs px-2 py-1 bg-surface border..."` buttons that each drifted a
 * pixel or a shade. Inconsistent affordances are the product register's clearest
 * tell: if Save looks different on two screens, one of them is wrong.
 *
 * Every variant carries all seven states — default, hover, focus, active,
 * disabled, loading, and (for `danger`) destructive intent. Shipping half of
 * them is what makes a UI feel unfinished without anyone being able to say why.
 */
const buttonVariants = cva(
  cn(
    'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md',
    'font-medium transition-colors duration-150 ease-out',
    'disabled:pointer-events-none disabled:opacity-50',
    // Icons in buttons should never be tab stops or fight the text baseline.
    '[&_svg]:pointer-events-none [&_svg]:shrink-0',
  ),
  {
    variants: {
      variant: {
        primary: 'bg-accent text-accent-ink hover:bg-accent-hover active:bg-accent-hover',
        secondary:
          'bg-surface text-ink border border-line hover:bg-surface-hover hover:border-line-strong',
        ghost: 'text-ink-muted hover:bg-surface-hover hover:text-ink',
        // Destructive actions must look destructive before they are clicked,
        // not only in the confirmation dialog.
        danger:
          'bg-surface text-danger border border-danger/25 hover:bg-danger-tint hover:border-danger/40',
        'danger-solid': 'bg-danger text-accent-ink hover:bg-danger-hover',
      },
      size: {
        sm: 'h-7 px-2 text-xs [&_svg]:size-3.5',
        md: 'h-8 px-3 text-sm [&_svg]:size-4',
        lg: 'h-9 px-4 text-base [&_svg]:size-4',
        // Square, for a lone icon. Explicit so nobody pads a text size down.
        'icon-sm': 'h-7 w-7 [&_svg]:size-3.5',
        icon: 'h-8 w-8 [&_svg]:size-4',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
  /** Shows a spinner and disables the button. Keeps its width — see below. */
  loading?: boolean
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, loading, children, disabled, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading ? (
          // The label stays, dimmed, with the spinner overlaid — swapping it for
          // "Saving…" changes the button's width mid-click and shifts whatever
          // sits beside it.
          <>
            <Loader2 className="animate-spin" aria-hidden />
            <span className="opacity-70">{children}</span>
          </>
        ) : (
          children
        )}
      </Comp>
    )
  },
)
Button.displayName = 'Button'
export { buttonVariants }

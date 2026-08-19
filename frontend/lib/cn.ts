import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Merge class names, with later Tailwind utilities beating earlier ones.
 *
 * Needed because variant components take a `className` from the caller, and
 * plain string concatenation leaves both `h-8` and `h-9` in the list — where the
 * winner is then decided by stylesheet order rather than by the caller.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

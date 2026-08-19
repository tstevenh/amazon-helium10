'use client'
import { useCallback, useMemo } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'

/**
 * Keep screen state (filters, date range, sort) in the URL query string.
 *
 * Filters used to live in useState, which meant they were lost the moment you
 * opened a campaign and pressed Back: the screen remounted with its defaults,
 * so "7 days, sorted by clicks" silently became "30 days, sorted by spend".
 * Anyone comparing several campaigns had to re-apply the filters every time.
 *
 * The URL is the right home for this. Back and Forward restore it for free
 * because the browser already remembers URLs, opening a row in a new tab
 * carries the filters with it, and a link can be pasted to a colleague and
 * show them the same view.
 *
 * Updates use router.replace, not push: typing in a search box must not stack
 * one history entry per keystroke, or Back would walk through them one letter
 * at a time instead of returning to the previous screen.
 *
 * Values equal to their default are dropped from the URL, so the common case
 * stays a clean /campaigns rather than a wall of redundant parameters.
 */
export function useUrlState<T extends Record<string, string>>(defaults: T) {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()

  const state = useMemo(() => {
    const out = { ...defaults }
    for (const key of Object.keys(defaults) as (keyof T)[]) {
      const raw = searchParams.get(String(key))
      if (raw !== null) out[key] = raw as T[keyof T]
    }
    return out
  }, [searchParams, defaults])

  const setState = useCallback(
    (patch: Partial<T>) => {
      const next = new URLSearchParams(searchParams.toString())
      for (const [key, value] of Object.entries({ ...state, ...patch })) {
        if (value === undefined || value === '' || value === defaults[key]) {
          next.delete(key)
        } else {
          next.set(key, String(value))
        }
      }
      const qs = next.toString()
      // scroll: false — changing a filter should not jump the page to the top
      // and lose the operator's place in a long table.
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
    },
    [searchParams, state, defaults, pathname, router],
  )

  return [state, setState] as const
}

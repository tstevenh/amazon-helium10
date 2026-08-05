'use client'
import { useCallback, useState } from 'react'
import { useAuth } from '@/context/AuthContext'
import { ApiError } from '@/lib/api'

/** Wraps an API call in loading/error state. Returns [call, loading, error, reset]. */
export function useApiCall<T>(
  fn: (token: string, ...args: unknown[]) => Promise<T>,
) {
  const { token } = useAuth()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const call = useCallback(
    async (...args: unknown[]): Promise<T | undefined> => {
      if (!token) return undefined
      setLoading(true)
      setError(null)
      try {
        const result = await fn(token, ...args)
        return result
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : 'Unexpected error'
        setError(msg)
        return undefined
      } finally {
        setLoading(false)
      }
    },
    [fn, token],
  )

  return { call, loading, error, clearError: () => setError(null) }
}

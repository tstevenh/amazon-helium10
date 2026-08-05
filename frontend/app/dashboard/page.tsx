'use client'
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'
import { LoadingState } from '@/components/ui/LoadingState'

export default function DashboardPage() {
  const { user, loading } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (!loading && !user) router.push('/login')
    // Dashboard not yet built — redirect to Campaign Manager for now
    if (!loading && user) router.push('/campaigns')
  }, [loading, user, router])

  return <LoadingState message="Loading…" />
}

'use client'
/**
 * AccountProfileContext — Sprint 1E
 *
 * Global foundation for all PPC OS modules.
 * Every page that needs to know "which account / which profile am I in?"
 * imports useAccountProfile() from here. No URL params required.
 *
 * State cascade:
 *   user authenticated
 *     → load all accounts
 *     → restore saved selection (localStorage) or auto-select first account
 *     → load profiles for selected account
 *     → restore saved profile or default to null (All Profiles)
 *
 * Persistence:
 *   localStorage key: ppc_os_selection  →  { accountId, profileId }
 *
 * Future module usage:
 *   const { currentAccountId, currentProfileId } = useAccountProfile()
 */
import {
  createContext, useContext, useEffect, useState, useCallback,
  useMemo, type ReactNode,
} from 'react'
import { api } from '@/lib/api'
import { useAuth } from '@/context/AuthContext'
import type { Account, Profile, ProfileCount } from '@/lib/types'

// ── Persistence ───────────────────────────────────────────────────────────

const STORAGE_KEY = 'ppc_os_selection'

interface SavedSelection {
  accountId: string | null
  profileId: string | null
}

function loadSaved(): SavedSelection {
  try {
    if (typeof window === 'undefined') return { accountId: null, profileId: null }
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { accountId: null, profileId: null }
    return JSON.parse(raw) as SavedSelection
  } catch {
    return { accountId: null, profileId: null }
  }
}

function saveSelection(sel: SavedSelection) {
  try {
    if (typeof window !== 'undefined')
      localStorage.setItem(STORAGE_KEY, JSON.stringify(sel))
  } catch { /* ignore write errors */ }
}

// ── Context shape ─────────────────────────────────────────────────────────

export interface AccountProfileContextValue {
  /** All accounts visible to this user */
  accounts: Account[]
  /** UUID of the currently selected account, or null if none loaded yet */
  currentAccountId: string | null
  /** Full Account object for currentAccountId */
  currentAccount: Account | null
  /** Profiles belonging to currentAccountId */
  profiles: Profile[]
  /** UUID of the selected profile, or null = "All Profiles" */
  currentProfileId: string | null
  /** Full Profile object for currentProfileId */
  currentProfile: Profile | null
  /** Set of profile IDs that belong to the current account (for client-side campaign filtering) */
  accountProfileIds: Set<string>
  /** True while the initial account list is loading */
  accountsLoading: boolean
  /** True while profiles are being fetched after an account change */
  profilesLoading: boolean
  /** Campaign count per marketplace — used to explain empty screens */
  profileCounts: ProfileCount[]
  /** Switch to a different account; resets profile to All */
  setCurrentAccount: (accountId: string) => void
  /** Set the active profile; null = All Profiles */
  setCurrentProfile: (profileId: string | null) => void
  /** Re-fetch profiles for current account (after a sync) */
  refreshProfiles: () => Promise<void>
}

const defaultCtx: AccountProfileContextValue = {
  accounts: [],
  currentAccountId: null,
  currentAccount: null,
  profiles: [],
  currentProfileId: null,
  currentProfile: null,
  accountProfileIds: new Set(),
  accountsLoading: true,
  profilesLoading: false,
  profileCounts: [],
  setCurrentAccount: () => {},
  setCurrentProfile: () => {},
  refreshProfiles: async () => {},
}

const AccountProfileContext = createContext<AccountProfileContextValue>(defaultCtx)

// ── Provider ──────────────────────────────────────────────────────────────

export function AccountProfileProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()

  const [accounts, setAccounts] = useState<Account[]>([])
  const [currentAccountId, setCurrentAccountId] = useState<string | null>(null)
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [currentProfileId, setCurrentProfileId] = useState<string | null>(null)
  const [accountsLoading, setAccountsLoading] = useState(true)
  const [profilesLoading, setProfilesLoading] = useState(false)
  // Campaign counts per marketplace, so an empty screen can explain itself.
  const [profileCounts, setProfileCounts] = useState<ProfileCount[]>([])

  // Load profiles for a given account id; returns the fetched list
  const fetchProfiles = useCallback(async (accountId: string): Promise<Profile[]> => {
    setProfilesLoading(true)
    try {
      const profs = await api.getProfiles(accountId)
      setProfiles(profs)
      // Non-fatal: without counts the empty state just falls back to its
      // generic message rather than naming the marketplace with data.
      api.getProfileCounts(accountId)
        .then(setProfileCounts)
        .catch(() => setProfileCounts([]))
      return profs
    } catch {
      setProfiles([])
      setProfileCounts([])
      return []
    } finally {
      setProfilesLoading(false)
    }
  }, [])

  // Bootstrap: runs when user becomes authenticated (or is cleared on logout)
  useEffect(() => {
    if (!user) {
      setAccounts([])
      setCurrentAccountId(null)
      setProfiles([])
      setCurrentProfileId(null)
      setAccountsLoading(false)
      return
    }

    let cancelled = false
    setAccountsLoading(true)

    api.listAccounts()
      .then(async (accts) => {
        if (cancelled) return
        setAccounts(accts)

        if (!accts.length) {
          setAccountsLoading(false)
          return
        }

        // Restore saved selection or default to first account
        const saved = loadSaved()
        const savedAccountValid = saved.accountId && accts.some(a => a.id === saved.accountId)
        const targetAccountId = savedAccountValid ? saved.accountId! : accts[0].id

        setCurrentAccountId(targetAccountId)

        // Load profiles for resolved account
        const profs = await api.getProfiles(targetAccountId).catch(() => [] as Profile[])
        if (cancelled) return
        setProfiles(profs)

        // Restore saved profile if still valid
        const savedProfileValid = saved.profileId && profs.some(p => p.id === saved.profileId)
        const targetProfileId = savedProfileValid ? saved.profileId! : null
        setCurrentProfileId(targetProfileId)

        // Persist resolved selection
        saveSelection({ accountId: targetAccountId, profileId: targetProfileId })
        setAccountsLoading(false)
      })
      .catch(() => {
        if (!cancelled) setAccountsLoading(false)
      })

    return () => { cancelled = true }
  }, [user])

  // Switch account — clear stale profiles immediately so accountProfileIds
  // becomes an empty Set; filter logic in consumers treats empty-while-loading
  // correctly (shows a loading state rather than an empty table or all campaigns).
  const setCurrentAccount = useCallback((accountId: string) => {
    setCurrentAccountId(accountId)
    setCurrentProfileId(null)
    setProfiles([])          // ← wipe stale profiles right now
    saveSelection({ accountId, profileId: null })
    fetchProfiles(accountId) // ← async; sets profilesLoading → false when done
  }, [fetchProfiles])

  // Switch profile
  const setCurrentProfile = useCallback((profileId: string | null) => {
    setCurrentProfileId(profileId)
    saveSelection({ accountId: currentAccountId, profileId })
  }, [currentAccountId])

  // Re-fetch profiles (called after syncing profiles from Amazon)
  const refreshProfiles = useCallback(async () => {
    if (currentAccountId) await fetchProfiles(currentAccountId)
  }, [currentAccountId, fetchProfiles])

  // Derived values
  const currentAccount = useMemo(
    () => accounts.find(a => a.id === currentAccountId) ?? null,
    [accounts, currentAccountId],
  )
  const currentProfile = useMemo(
    () => profiles.find(p => p.id === currentProfileId) ?? null,
    [profiles, currentProfileId],
  )
  const accountProfileIds = useMemo(
    () => new Set(profiles.map(p => p.id)),
    [profiles],
  )

  const value: AccountProfileContextValue = {
    accounts,
    currentAccountId,
    currentAccount,
    profiles,
    currentProfileId,
    currentProfile,
    accountProfileIds,
    accountsLoading,
    profilesLoading,
    profileCounts,
    setCurrentAccount,
    setCurrentProfile,
    refreshProfiles,
  }

  return (
    <AccountProfileContext.Provider value={value}>
      {children}
    </AccountProfileContext.Provider>
  )
}

// ── Hook ──────────────────────────────────────────────────────────────────

/**
 * useAccountProfile()
 *
 * Primary hook for all PPC OS modules.
 *
 * Usage:
 *   const { currentAccountId, currentProfileId, profiles } = useAccountProfile()
 *
 * Future modules (Dashboard, Search Terms, Rules, Dayparting, etc.) call this
 * hook to know which account/profile is active — no URL params needed.
 */
export function useAccountProfile(): AccountProfileContextValue {
  return useContext(AccountProfileContext)
}

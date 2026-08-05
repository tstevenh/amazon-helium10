'use client'
/**
 * GlobalHeader — Sprint 1E
 *
 * Always-visible application header containing:
 *   [PPC OS]  [Account ▼]  [Profile ▼]  ────────  [email | Sign out]
 *
 * Replaces Nav. Consumes both AuthContext and AccountProfileContext.
 * Every future module sees the current account/profile at all times.
 */
import { useAuth } from '@/context/AuthContext'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { usePathname } from 'next/navigation'

/** Format a profile for the dropdown label */
function profileLabel(p: { country_code: string | null; currency_code: string | null; marketplace_code: string }): string {
  if (p.country_code && p.currency_code) return `${p.country_code} – ${p.currency_code}`
  if (p.country_code) return p.country_code
  return p.marketplace_code
}

export function GlobalHeader() {
  const { user, logout } = useAuth()
  const {
    accounts,
    currentAccountId,
    profiles,
    currentProfileId,
    accountsLoading,
    profilesLoading,
    setCurrentAccount,
    setCurrentProfile,
  } = useAccountProfile()
  const pathname = usePathname()

  // Don't render the selectors on the login page
  const isLoginPage = pathname === '/login'

  return (
    <header className="bg-gray-900 text-white sticky top-0 z-50 shadow-md">
      <div className="max-w-7xl mx-auto px-4 flex items-center gap-3 h-14">
        {/* App identity */}
        <span className="font-bold text-sm tracking-wide text-blue-400 shrink-0 mr-2">
          PPC OS
        </span>

        {/* Account + Profile selectors — hidden on login page */}
        {user && !isLoginPage && (
          <>
            {/* Account selector */}
            <div className="flex items-center gap-1.5 shrink-0">
              <span className="text-gray-500 text-xs hidden sm:inline">Account</span>
              <select
                value={currentAccountId ?? ''}
                onChange={e => setCurrentAccount(e.target.value)}
                disabled={accountsLoading || accounts.length === 0}
                className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700
                           focus:outline-none focus:border-blue-500 disabled:opacity-50
                           max-w-[180px] truncate"
                aria-label="Select account"
              >
                {accountsLoading && (
                  <option value="">Loading…</option>
                )}
                {!accountsLoading && accounts.length === 0 && (
                  <option value="">No accounts</option>
                )}
                {accounts.map(a => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </select>
            </div>

            {/* Divider */}
            <span className="text-gray-600 hidden sm:inline">›</span>

            {/* Profile selector */}
            <div className="flex items-center gap-1.5 shrink-0">
              <span className="text-gray-500 text-xs hidden sm:inline">Marketplace</span>
              <select
                value={currentProfileId ?? ''}
                onChange={e => setCurrentProfile(e.target.value || null)}
                disabled={profilesLoading || !currentAccountId}
                className="bg-gray-800 text-white text-sm rounded px-2 py-1 border border-gray-700
                           focus:outline-none focus:border-blue-500 disabled:opacity-50
                           max-w-[160px] truncate"
                aria-label="Select marketplace"
              >
                <option value="">All Profiles</option>
                {profilesLoading && <option value="" disabled>Loading…</option>}
                {!profilesLoading && profiles.map(p => (
                  <option key={p.id} value={p.id}>{profileLabel(p)}</option>
                ))}
              </select>
            </div>
          </>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* User menu */}
        {user && (
          <div className="flex items-center gap-3 shrink-0">
            <span className="text-gray-400 text-sm hidden md:inline truncate max-w-[180px]">
              {user.email}
            </span>
            <button
              onClick={logout}
              className="text-gray-400 hover:text-white text-sm transition-colors"
            >
              Sign out
            </button>
          </div>
        )}
      </div>

      {/* Active context indicator bar — subtle coloured bottom border when selection is active */}
      {user && !isLoginPage && currentAccountId && (
        <div className="h-0.5 bg-blue-600 opacity-60" />
      )}
    </header>
  )
}

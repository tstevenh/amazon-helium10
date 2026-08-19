'use client'
/**
 * Application header: identity, scope selectors, account menu.
 *
 * The scope selectors are the most consequential control in the app. Picking the
 * wrong marketplace makes every screen look empty, and this project has already
 * shipped a bug where "No rules yet" actually meant "wrong marketplace". So they
 * are readable body-sized controls with visible labels, not 12px gray-on-dark.
 *
 * The bar itself is light now. A dark header over a light sidebar over a light
 * canvas is three surfaces pretending to be one app; the shell reads as a single
 * plane with a hairline separating chrome from content. It also removes the
 * washed-out gray-on-near-black label text the old header had.
 */
import { usePathname } from 'next/navigation'
import { ChevronRight, LogOut } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { useAccountProfile } from '@/context/AccountProfileContext'
import { Select } from '@/components/ui/Field'
import { Button } from '@/components/ui/Button'

function profileLabel(p: {
  country_code: string | null
  currency_code: string | null
  marketplace_code: string
}): string {
  if (p.country_code && p.currency_code) return `${p.country_code} · ${p.currency_code}`
  if (p.country_code) return p.country_code
  return p.marketplace_code
}

export function GlobalHeader() {
  const { user, logout } = useAuth()
  const {
    accounts, currentAccountId, profiles, currentProfileId,
    accountsLoading, profilesLoading, setCurrentAccount, setCurrentProfile,
  } = useAccountProfile()
  const pathname = usePathname()
  const isLoginPage = pathname === '/login'

  return (
    <header className="sticky top-0 z-sticky border-b border-hairline bg-surface">
      {/* No max-width here on purpose: the old header centred its contents in a
          7xl container while the sidebar sat flush left, so the wordmark never
          lined up with the navigation beneath it. */}
      <div className="flex h-14 items-center gap-3 px-4">
        <span className="mr-1 shrink-0 text-sm font-semibold tracking-tight text-ink">
          PPC&nbsp;OS
        </span>

        {user && !isLoginPage && (
          <div className="flex min-w-0 items-center gap-2">
            <label className="flex min-w-0 items-center gap-1.5">
              <span className="hidden shrink-0 text-xs text-ink-subtle sm:inline">Account</span>
              <Select
                value={currentAccountId ?? ''}
                onChange={e => setCurrentAccount(e.target.value)}
                disabled={accountsLoading || accounts.length === 0}
                className="max-w-[200px]"
                aria-label="Account"
              >
                {accountsLoading && <option value="">Loading…</option>}
                {!accountsLoading && accounts.length === 0 && (
                  <option value="">No accounts</option>
                )}
                {accounts.map(a => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
              </Select>
            </label>

            <ChevronRight size={14} className="shrink-0 text-ink-faint" aria-hidden />

            <label className="flex min-w-0 items-center gap-1.5">
              <span className="hidden shrink-0 text-xs text-ink-subtle sm:inline">Marketplace</span>
              <Select
                value={currentProfileId ?? ''}
                onChange={e => setCurrentProfile(e.target.value || null)}
                disabled={profilesLoading || !currentAccountId}
                className="max-w-[170px]"
                aria-label="Marketplace"
              >
                <option value="">All marketplaces</option>
                {profilesLoading && <option value="" disabled>Loading…</option>}
                {!profilesLoading && profiles.map(p => (
                  <option key={p.id} value={p.id}>{profileLabel(p)}</option>
                ))}
              </Select>
            </label>
          </div>
        )}

        <div className="flex-1" />

        {user && (
          <div className="flex shrink-0 items-center gap-2">
            <span className="hidden max-w-[200px] truncate text-xs text-ink-muted md:inline">
              {user.email}
            </span>
            <Button variant="ghost" size="sm" onClick={logout}>
              <LogOut aria-hidden />
              Sign out
            </Button>
          </div>
        )}
      </div>
    </header>
  )
}

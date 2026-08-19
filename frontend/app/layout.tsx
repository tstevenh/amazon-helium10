import type { Metadata } from 'next'
import { Suspense } from 'react'
import './globals.css'
import { AuthProvider } from '@/context/AuthContext'
import { AccountProfileProvider } from '@/context/AccountProfileContext'
import { GlobalHeader } from '@/components/layout/GlobalHeader'
import { SideNav } from '@/components/layout/SideNav'

export const metadata: Metadata = {
  title: 'PPC OS',
  description: 'Amazon PPC Operating System',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-canvas">
        <AuthProvider>
          <AccountProfileProvider>
            {/* Sticky global header: account/profile selectors + user menu */}
            <GlobalHeader />
            {/*
             * Two-column shell: sidebar (module nav) + main content.
             * SideNav renders null on /login, so the login page is full-width.
             */}
            <div className="flex min-h-[calc(100vh-3.5rem)]">
              <SideNav />
              {/* No max-width cap: these tables have up to 15 numeric columns,
                  and a 1152px centred column forced them to scroll sideways
                  while empty space sat to the right. Prose inside a screen is
                  capped where it matters instead. */}
              {/*
               * Suspense boundary is REQUIRED, not stylistic.
               *
               * Five screens keep their filters in the URL via useUrlState, which
               * calls useSearchParams(). During `next build` Next prerenders each
               * route, and a component reading search params has nothing to read
               * yet — so it must be able to suspend. Without a boundary the
               * production build fails with "useSearchParams() should be wrapped
               * in a suspense boundary" on /campaigns, /keywords, /ad-groups,
               * /search-terms and /suggestions.
               *
               * `next dev` does not enforce this, so the whole thing passed
               * locally and only broke on the server's build. It is placed here
               * rather than in each page so the next screen to adopt useUrlState
               * cannot reintroduce it.
               *
               * The fallback is deliberately empty: these screens are behind auth
               * and fetch everything client-side, so any skeleton here would
               * flash for a frame and be replaced.
               */}
              <main className="min-w-0 flex-1 px-5 py-5">
                <Suspense fallback={null}>{children}</Suspense>
              </main>
            </div>
          </AccountProfileProvider>
        </AuthProvider>
      </body>
    </html>
  )
}

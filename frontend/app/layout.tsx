import type { Metadata } from 'next'
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
              <main className="min-w-0 flex-1 px-5 py-5">{children}</main>
            </div>
          </AccountProfileProvider>
        </AuthProvider>
      </body>
    </html>
  )
}

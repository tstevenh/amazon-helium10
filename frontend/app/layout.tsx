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
      <body className="min-h-screen bg-gray-50">
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
              <main className="flex-1 min-w-0 px-6 py-6">
                <div className="max-w-6xl mx-auto">
                  {children}
                </div>
              </main>
            </div>
          </AccountProfileProvider>
        </AuthProvider>
      </body>
    </html>
  )
}

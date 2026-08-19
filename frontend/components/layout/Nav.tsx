'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'

const links = [
  { href: '/accounts', label: 'Accounts' },
  { href: '/campaigns', label: 'Campaigns' },
]

export function Nav() {
  const pathname = usePathname()
  const { user, logout } = useAuth()

  return (
    <nav className="bg-ink text-white">
      <div className="max-w-7xl mx-auto px-4 flex items-center h-14 gap-8">
        <span className="font-bold text-sm tracking-wide text-accent shrink-0">
          PPC OS
        </span>
        <div className="flex items-center gap-1 flex-1">
          {links.map(l => (
            <Link
              key={l.href}
              href={l.href}
              className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                pathname.startsWith(l.href)
                  ? 'bg-ink-muted text-white'
                  : 'text-ink-faint hover:bg-ink hover:text-white'
              }`}
            >
              {l.label}
            </Link>
          ))}
        </div>
        {user && (
          <div className="flex items-center gap-3 text-sm">
            <span className="text-ink-subtle">{user.email}</span>
            <button
              onClick={logout}
              className="text-ink-subtle hover:text-white transition-colors"
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </nav>
  )
}

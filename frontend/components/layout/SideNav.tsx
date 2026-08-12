'use client'
/**
 * SideNav — Sprint 4
 *
 * Left sidebar navigation for PPC OS.
 * Organised as a module list mirroring the target Helium10-style layout.
 */
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useAuth } from '@/context/AuthContext'

interface NavItem {
  label: string
  href: string
  icon: string   // emoji stand-in; replace with SVG icons in a later sprint
  badge?: string // e.g. "Soon"
  /** Hidden entirely for non-admins — they cannot call the endpoints anyway. */
  adminOnly?: boolean
  disabled?: boolean
}

const MAIN_MODULES: NavItem[] = [
  { label: 'Campaign Manager', href: '/campaigns',  icon: '📊' },
  { label: 'Ad Groups',        href: '/ad-groups',  icon: '🗂️' },
  { label: 'Keywords',         href: '/keywords',   icon: '🔑' },
  { label: 'Dashboard',        href: '/dashboard',  icon: '🏠', badge: 'Soon', disabled: true },
  { label: 'Search Terms',     href: '/search-terms', icon: '🔍' },
  { label: 'Suggestions',      href: '/suggestions', icon: '💡' },
  { label: 'Rules',            href: '/rules',      icon: '⚙️' },
  { label: 'Logs',             href: '/logs',       icon: '📜' },
]

const SETTINGS_MODULES: NavItem[] = [
  { label: 'Accounts', href: '/accounts', icon: '🏪' },
  { label: 'Sync Monitor', href: '/sync-monitor', icon: '🩺' },
  { label: 'Users',    href: '/users',    icon: '👥', adminOnly: true },
]

function NavLink({ item }: { item: NavItem }) {
  const pathname = usePathname()
  const isActive = !item.disabled && pathname.startsWith(item.href)

  if (item.disabled) {
    return (
      <div className="flex items-center gap-2.5 px-3 py-2 rounded text-sm text-gray-500 cursor-not-allowed select-none">
        <span className="text-base leading-none">{item.icon}</span>
        <span className="flex-1">{item.label}</span>
        {item.badge && (
          <span className="text-[10px] bg-gray-100 text-gray-400 rounded px-1.5 py-0.5">
            {item.badge}
          </span>
        )}
      </div>
    )
  }

  return (
    <Link
      href={item.href}
      className={`flex items-center gap-2.5 px-3 py-2 rounded text-sm font-medium transition-colors ${
        isActive
          ? 'bg-blue-50 text-blue-700'
          : 'text-gray-700 hover:bg-gray-100 hover:text-gray-900'
      }`}
    >
      <span className="text-base leading-none">{item.icon}</span>
      <span className="flex-1">{item.label}</span>
    </Link>
  )
}

export function SideNav() {
  const { user } = useAuth()
  const pathname = usePathname()

  // Don't render on the login page
  if (!user || pathname === '/login') return null

  return (
    <aside className="w-52 shrink-0 min-h-[calc(100vh-3.5rem)] bg-white border-r border-gray-200 py-4 px-2">
      {/* Main modules */}
      <div className="mb-6">
        <p className="px-3 mb-1 text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
          Modules
        </p>
        <nav className="space-y-0.5">
          {MAIN_MODULES.map(item => (
            <NavLink key={item.href} item={item} />
          ))}
        </nav>
      </div>

      {/* Settings section */}
      <div>
        <p className="px-3 mb-1 text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
          Settings
        </p>
        <nav className="space-y-0.5">
          {SETTINGS_MODULES
            .filter(item => !item.adminOnly || user.role === 'admin')
            .map(item => (
              <NavLink key={item.href} item={item} />
            ))}
        </nav>
      </div>
    </aside>
  )
}

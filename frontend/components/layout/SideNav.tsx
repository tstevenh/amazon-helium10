'use client'
/**
 * Left navigation.
 *
 * Two changes beyond the visual pass:
 *
 * 1. Emoji icons are gone. Fifteen of them, which rendered differently on every
 *    OS, refused to sit on the text baseline, and made a tool that moves real
 *    advertising money look like a hobby app. Lucide at 16px, stroke 1.75, on the
 *    same optical grid as the labels.
 *
 * 2. The eleven "Modules" are grouped by the job being done. The old flat list
 *    put Dashboard fourth, between Keywords and Search Terms, so the overview sat
 *    in the middle of the drill-downs. The order now follows how the work
 *    actually runs: check the data, read it, act on it, research, audit.
 */
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  Activity, BarChart3, Bell, Clock, FileClock, FlaskConical, Gauge,
  KeyRound, Lightbulb, Layers, MapPin, Search, Settings2, Store, Users,
  type LucideIcon,
} from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { cn } from '@/lib/cn'

interface NavItem {
  label: string
  href: string
  icon: LucideIcon
  /** Hidden entirely for non-admins — they cannot call the endpoints anyway. */
  adminOnly?: boolean
}

interface NavGroup {
  /** Omitted for the first group: a heading above a single Dashboard link is
   *  noise, and the sidebar should not open with a label. */
  label?: string
  items: NavItem[]
}

const GROUPS: NavGroup[] = [
  { items: [{ label: 'Dashboard', href: '/dashboard', icon: Gauge }] },
  {
    label: 'Performance',
    items: [
      { label: 'Campaigns',    href: '/campaigns',    icon: BarChart3 },
      { label: 'Ad Groups',    href: '/ad-groups',    icon: Layers },
      { label: 'Keywords',     href: '/keywords',     icon: KeyRound },
      { label: 'Search Terms', href: '/search-terms', icon: Search },
      { label: 'Placements',   href: '/placements',   icon: MapPin },
    ],
  },
  {
    label: 'Automation',
    items: [
      { label: 'Suggestions', href: '/suggestions', icon: Lightbulb },
      { label: 'Rules',       href: '/rules',       icon: Settings2 },
      { label: 'Dayparting',  href: '/dayparting',  icon: Clock },
    ],
  },
  {
    label: 'Research',
    items: [{ label: 'Keyword Intel', href: '/keyword-intel', icon: FlaskConical }],
  },
  {
    label: 'Activity',
    items: [
      { label: 'Change Log',    href: '/logs',          icon: FileClock },
      { label: 'Sync Monitor',  href: '/sync-monitor',  icon: Activity },
      { label: 'Notifications', href: '/notifications', icon: Bell },
    ],
  },
  {
    label: 'Settings',
    items: [
      { label: 'Accounts', href: '/accounts', icon: Store },
      { label: 'Users',    href: '/users',    icon: Users, adminOnly: true },
    ],
  },
]

/**
 * Exact match, or a genuine child route.
 *
 * A bare startsWith() would light up /keywords while sitting on /keywords-foo,
 * and there is no reason to leave that trap in place for the next route someone
 * adds.
 */
function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(href + '/')
}

function NavLink({ item }: { item: NavItem }) {
  const pathname = usePathname()
  const active = isActive(pathname, item.href)
  const Icon = item.icon

  return (
    <Link
      href={item.href}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm',
        'transition-colors duration-150 ease-out',
        active
          ? 'bg-accent-weak font-medium text-accent'
          : 'text-ink-muted hover:bg-surface-hover hover:text-ink',
      )}
    >
      <Icon
        size={16}
        strokeWidth={1.75}
        aria-hidden
        // The icon follows the label's state rather than carrying its own
        // colour, so an inactive row reads as one object instead of two.
        className={cn('shrink-0', active ? 'text-accent' : 'text-ink-faint group-hover:text-ink-subtle')}
      />
      <span className="truncate">{item.label}</span>
    </Link>
  )
}

export function SideNav() {
  const { user } = useAuth()
  const pathname = usePathname()

  if (!user || pathname === '/login') return null

  return (
    <aside
      className={cn(
        'w-52 shrink-0 border-r border-hairline bg-sidebar',
        // Sticky rather than tall-and-scrolling: at 16 destinations the list
        // fits, and navigation should not move when a 25-row table scrolls.
        'sticky top-14 h-[calc(100vh-3.5rem)] overflow-y-auto px-2 py-3',
      )}
    >
      <nav className="space-y-4">
        {GROUPS.map((group, i) => {
          const items = group.items.filter(
            item => !item.adminOnly || user.role === 'admin',
          )
          if (items.length === 0) return null
          return (
            <div key={group.label ?? `group-${i}`}>
              {group.label && (
                // Sentence case, not uppercase-tracked. Six all-caps headings in
                // a 200px column is more shouting than structure.
                <p className="px-2.5 pb-1 text-2xs font-medium text-ink-faint">
                  {group.label}
                </p>
              )}
              <div className="space-y-0.5">
                {items.map(item => (
                  <NavLink key={item.href} item={item} />
                ))}
              </div>
            </div>
          )
        })}
      </nav>
    </aside>
  )
}

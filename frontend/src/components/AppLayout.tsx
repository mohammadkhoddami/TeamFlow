import {
  BarChart3,
  Clock,
  FolderKanban,
  LayoutDashboard,
  ListTodo,
  LogOut,
  Menu,
  ScrollText,
  Settings,
  Tags,
  Users,
  Webhook,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useAuth } from '../contexts/auth'
import { useOrganizations } from '../lib/hooks'
import { isAdmin } from '../lib/types'
import { cn } from '../lib/utils'
import { GlobalSearch } from './GlobalSearch'
import { NotificationBell } from './NotificationBell'
import { useOrg } from './OrgLayout'
import { ThemeToggle } from './ThemeToggle'
import { Avatar } from './ui'

const NAV_ITEMS = [
  { to: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: 'projects', label: 'Projects', icon: FolderKanban },
  { to: 'tasks', label: 'Tasks', icon: ListTodo },
  { to: 'reports', label: 'Reports', icon: BarChart3 },
  { to: 'timesheet', label: 'Timesheet', icon: Clock },
  { to: 'members', label: 'Members', icon: Users },
  { to: 'labels', label: 'Labels', icon: Tags },
  { to: 'webhooks', label: 'Webhooks', icon: Webhook, adminOnly: true },
  { to: 'audit', label: 'Audit log', icon: ScrollText, adminOnly: true },
  { to: 'settings', label: 'Settings', icon: Settings },
] as const

export function AppLayout() {
  const { org, role } = useOrg()
  const { user, logout } = useAuth()
  const organizations = useOrganizations()
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)

  const sidebar = (
    <div className="flex h-full flex-col bg-white">
      <div className="border-b border-slate-200 px-4 py-4">
        <p className="text-sm font-bold tracking-tight text-brand-700">TeamFlow</p>
        <select
          className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm font-medium text-slate-800 focus:border-brand-500 focus:outline-none"
          value={org.slug}
          onChange={(event) => {
            if (event.target.value === '__all__') {
              navigate('/organizations')
            } else {
              navigate(`/org/${event.target.value}/dashboard`)
            }
          }}
        >
          <option value="__all__">All workspaces…</option>
          {organizations.data?.map((entry) => (
            <option key={entry.organization.id} value={entry.organization.slug}>
              {entry.organization.name}
            </option>
          ))}
        </select>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-4">
        {NAV_ITEMS.filter((item) => !('adminOnly' in item && item.adminOnly) || isAdmin(role)).map(
          (item) => (
            <NavLink
              key={item.to}
              to={`/org/${org.slug}/${item.to}`}
              onClick={() => setMobileOpen(false)}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-brand-50 text-brand-700'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          ),
        )}
      </nav>

      <div className="border-t border-slate-200 p-3">
        <NavLink
          to="/invitations"
          onClick={() => setMobileOpen(false)}
          className="block rounded-lg px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
        >
          My invitations
        </NavLink>
        <div className="mt-1 flex items-center gap-2.5 rounded-lg px-3 py-2">
          <Avatar name={user?.full_name || user?.email || '?'} email={user?.email} size="sm" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-800">
              {user?.full_name || 'Account'}
            </p>
            <p className="truncate text-xs text-slate-500">{user?.email}</p>
          </div>
          <button
            onClick={() => void logout()}
            title="Log out"
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 border-r border-slate-200 md:block">{sidebar}</aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div className="w-64 shadow-xl">{sidebar}</div>
          <div className="flex-1 bg-slate-900/40" onClick={() => setMobileOpen(false)} />
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-2.5 md:px-6">
          <div className="flex items-center gap-2">
            <button
              className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 md:hidden"
              onClick={() => setMobileOpen((value) => !value)}
              aria-label="Toggle navigation"
            >
              {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
            <div>
              <p className="text-sm font-semibold text-slate-900">{org.name}</p>
              <p className="text-xs capitalize text-slate-500">{role} workspace</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <GlobalSearch />
            <ThemeToggle />
            <NotificationBell />
          </div>
        </header>

        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

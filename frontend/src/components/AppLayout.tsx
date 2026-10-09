import {
  BarChart3,
  Bot,
  Clock,
  FolderKanban,
  Gauge,
  KeyRound,
  LayoutDashboard,
  ListTodo,
  LogOut,
  Menu,
  Plug,
  Puzzle,
  ScrollText,
  Settings,
  Tags,
  Target,
  Users,
  Webhook,
  X,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useAuth } from '../contexts/auth'
import { useOrganizations } from '../lib/hooks'
import { useI18n } from '../lib/i18n'
import { isAdmin, ROLE_LABELS, type MembershipRole } from '../lib/types'
import { cn } from '../lib/utils'
import { GlobalSearch } from './GlobalSearch'
import { LanguageToggle } from './LanguageToggle'
import { NotificationBell } from './NotificationBell'
import { useOrg } from './OrgLayout'
import { ThemeToggle } from './ThemeToggle'
import { Avatar } from './ui'

const NAV_ITEMS = [
  { to: 'dashboard', label: 'nav.dashboard', icon: LayoutDashboard },
  { to: 'projects', label: 'nav.projects', icon: FolderKanban },
  { to: 'tasks', label: 'nav.tasks', icon: ListTodo },
  { to: 'goals', label: 'nav.goals', icon: Target },
  { to: 'dashboards', label: 'nav.dashboards', icon: Gauge },
  { to: 'reports', label: 'nav.reports', icon: BarChart3 },
  { to: 'automations', label: 'nav.automations', icon: Bot },
  { to: 'integrations', label: 'nav.integrations', icon: Plug },
  { to: 'plugins', label: 'nav.plugins', icon: Puzzle },
  { to: 'timesheet', label: 'nav.timesheet', icon: Clock },
  { to: 'members', label: 'nav.members', icon: Users },
  { to: 'labels', label: 'nav.labels', icon: Tags },
  { to: 'webhooks', label: 'nav.webhooks', icon: Webhook, adminOnly: true },
  { to: 'api-tokens', label: 'nav.apiTokens', icon: KeyRound },
  { to: 'audit', label: 'nav.audit', icon: ScrollText, adminOnly: true },
  { to: 'settings', label: 'nav.settings', icon: Settings },
] as const

export function AppLayout() {
  const { org, role } = useOrg()
  const { user, logout } = useAuth()
  const { t } = useI18n()
  const organizations = useOrganizations()
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)
  const roleLabel = t(`role.${role}`, ROLE_LABELS[role as MembershipRole])

  const sidebar = (
    <div className="flex h-full flex-col bg-white">
      <div className="border-b border-slate-200 px-4 py-4">
        <p className="text-sm font-bold tracking-tight text-brand-700">
          {t('common.brand', 'TeamFlow')}
        </p>
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
          <option value="__all__">{t('layout.allWorkspaces', 'All workspaces…')}</option>
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
              {t(item.label)}
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
          {t('layout.myInvitations', 'My invitations')}
        </NavLink>
        <div className="mt-1 flex items-center gap-2.5 rounded-lg px-3 py-2">
          <Avatar name={user?.full_name || user?.email || '?'} email={user?.email} size="sm" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-800">
              {user?.full_name || t('layout.account', 'Account')}
            </p>
            <p className="truncate text-xs text-slate-500">{user?.email}</p>
          </div>
          <button
            onClick={() => void logout()}
            title={t('layout.logOut', 'Log out')}
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
              aria-label={t('layout.toggleNavigation', 'Toggle navigation')}
            >
              {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
            <div>
              <p className="text-sm font-semibold text-slate-900">{org.name}</p>
              <p className="text-xs capitalize text-slate-500">
                {t('layout.roleWorkspace', '{role} workspace', { role: roleLabel })}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <GlobalSearch />
            <LanguageToggle />
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

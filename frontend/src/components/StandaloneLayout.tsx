import { LogOut } from 'lucide-react'
import { Link, NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../contexts/auth'
import { useI18n } from '../lib/i18n'
import { cn } from '../lib/utils'
import { Avatar } from './ui'

export function StandaloneLayout() {
  const { user, logout } = useAuth()
  const { t } = useI18n()

  return (
    <div className="flex min-h-full flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <Link to="/organizations" className="text-sm font-bold tracking-tight text-brand-700">
            {t('common.brand', 'TeamFlow')}
          </Link>
          <nav className="flex items-center gap-1">
            <NavLink
              to="/invitations"
              className={({ isActive }) =>
                cn(
                  'rounded-lg px-3 py-1.5 text-sm font-medium',
                  isActive ? 'bg-brand-50 text-brand-700' : 'text-slate-600 hover:bg-slate-100',
                )
              }
            >
              {t('layout.invitations', 'Invitations')}
            </NavLink>
            <div className="ml-2 flex items-center gap-2 border-l border-slate-200 pl-3">
              <Avatar name={user?.full_name || user?.email || '?'} email={user?.email} size="sm" />
              <span className="hidden text-sm text-slate-600 sm:block">
                {user?.full_name || user?.email}
              </span>
              <button
                onClick={() => void logout()}
                title={t('layout.logOut', 'Log out')}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}

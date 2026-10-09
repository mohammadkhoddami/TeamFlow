import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '../contexts/auth'
import { useI18n } from '../lib/i18n'
import { PageSpinner } from './ui'

export function ProtectedRoute() {
  const { user, loading } = useAuth()
  const { t } = useI18n()
  const location = useLocation()

  if (loading) return <PageSpinner label={t('layout.restoringSession', 'Restoring session…')} />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Outlet />
}

export function GuestRoute() {
  const { user, loading } = useAuth()
  const { t } = useI18n()
  if (loading) return <PageSpinner label={t('common.loading', 'Loading…')} />
  if (user) return <Navigate to="/organizations" replace />
  return <Outlet />
}

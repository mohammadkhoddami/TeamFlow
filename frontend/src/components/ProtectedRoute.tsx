import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '../contexts/auth'
import { PageSpinner } from './ui'

export function ProtectedRoute() {
  const { user, loading } = useAuth()
  const location = useLocation()

  if (loading) return <PageSpinner label="Restoring session…" />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Outlet />
}

export function GuestRoute() {
  const { user, loading } = useAuth()
  if (loading) return <PageSpinner label="Loading…" />
  if (user) return <Navigate to="/organizations" replace />
  return <Outlet />
}

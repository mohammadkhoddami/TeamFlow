import { createContext, useContext, useEffect } from 'react'
import { Navigate, Outlet, useParams } from 'react-router-dom'

import { applyAccent } from '../lib/accent'
import { useOrgMembers, useOrganizations } from '../lib/hooks'
import { useI18n } from '../lib/i18n'
import type { MembershipRead, MembershipRole, OrganizationRead } from '../lib/types'
import { ErrorState, PageSpinner } from './ui'

interface OrgContextValue {
  org: OrganizationRead
  role: MembershipRole
  members: MembershipRead[]
  membersLoading: boolean
}

const OrgContext = createContext<OrgContextValue | null>(null)

export function useOrg(): OrgContextValue {
  const context = useContext(OrgContext)
  if (!context) throw new Error('useOrg must be used inside an org route')
  return context
}

/** Like useOrg, but returns null outside org routes (shared components). */
export function useOrgOptional(): OrgContextValue | null {
  return useContext(OrgContext)
}

export function OrgLayout() {
  const { slug } = useParams<{ slug: string }>()
  const organizations = useOrganizations()
  const members = useOrgMembers(slug)
  const { t } = useI18n()

  const match = organizations.data?.find((entry) => entry.organization.slug === slug)

  // Workspace accent overrides the Tailwind brand ramp while inside the org.
  useEffect(() => {
    if (!match) return
    applyAccent(match.organization.accent_color)
    return () => applyAccent(null)
  }, [match])

  if (organizations.isLoading) {
    return <PageSpinner label={t('layout.loadingWorkspace', 'Loading workspace…')} />
  }
  if (organizations.isError) {
    return (
      <div className="mx-auto max-w-lg p-6">
        <ErrorState
          message={t('layout.loadWorkspacesError', 'Could not load your workspaces.')}
          onRetry={() => void organizations.refetch()}
        />
      </div>
    )
  }

  if (!match) return <Navigate to="/organizations" replace />

  return (
    <OrgContext.Provider
      value={{
        org: match.organization,
        role: match.role,
        members: members.data ?? [],
        membersLoading: members.isLoading,
      }}
    >
      <Outlet />
    </OrgContext.Provider>
  )
}

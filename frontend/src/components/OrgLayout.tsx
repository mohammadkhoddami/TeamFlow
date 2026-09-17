import { createContext, useContext } from 'react'
import { Navigate, Outlet, useParams } from 'react-router-dom'

import { useOrgMembers, useOrganizations } from '../lib/hooks'
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

export function OrgLayout() {
  const { slug } = useParams<{ slug: string }>()
  const organizations = useOrganizations()
  const members = useOrgMembers(slug)

  if (organizations.isLoading) return <PageSpinner label="Loading workspace…" />
  if (organizations.isError) {
    return (
      <div className="mx-auto max-w-lg p-6">
        <ErrorState message="Could not load your workspaces." onRetry={() => void organizations.refetch()} />
      </div>
    )
  }

  const match = organizations.data?.find((entry) => entry.organization.slug === slug)
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

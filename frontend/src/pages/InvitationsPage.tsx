import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MailOpen } from 'lucide-react'

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  PageSpinner,
} from '../components/ui'
import { useToast } from '../contexts/toast'
import { ApiError, invitationsApi } from '../lib/api'
import { qk, useMyInvitations } from '../lib/hooks'
import { ROLE_LABELS, type MembershipRole } from '../lib/types'
import { formatDate } from '../lib/utils'

export function InvitationsPage() {
  const invitations = useMyInvitations()
  const queryClient = useQueryClient()
  const toast = useToast()

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.invitationsMine })
    void queryClient.invalidateQueries({ queryKey: qk.orgs })
  }

  const accept = useMutation({
    mutationFn: invitationsApi.accept,
    onSuccess: () => {
      invalidate()
      toast.success('Invitation accepted')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not accept invite'),
  })

  const decline = useMutation({
    mutationFn: invitationsApi.decline,
    onSuccess: () => {
      invalidate()
      toast.success('Invitation declined')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not decline invite'),
  })

  const pending = invitations.data?.filter((invitation) => invitation.status === 'pending') ?? []

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">My invitations</h1>
        <p className="text-sm text-slate-500">Workspaces you've been invited to join.</p>
      </div>

      {invitations.isLoading && <PageSpinner />}
      {invitations.isError && (
        <ErrorState
          message="Could not load invitations."
          onRetry={() => void invitations.refetch()}
        />
      )}

      {invitations.data && pending.length === 0 && (
        <EmptyState
          icon={<MailOpen className="h-8 w-8" />}
          title="No pending invitations"
          description="When someone invites you, it will appear here."
        />
      )}

      <div className="space-y-3">
        {pending.map((invitation) => (
          <Card key={invitation.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div>
              <div className="flex items-center gap-2">
                <p className="font-medium text-slate-800">
                  {invitation.organization_name ?? 'Workspace'}
                </p>
                <Badge className="bg-brand-50 text-brand-700">
                  {ROLE_LABELS[invitation.role as MembershipRole] ?? invitation.role}
                </Badge>
              </div>
              <p className="mt-0.5 text-xs text-slate-500">
                Invited {formatDate(invitation.created_at)} · {invitation.email}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => decline.mutate(invitation.id)}
                loading={decline.isPending}
              >
                Decline
              </Button>
              <Button
                size="sm"
                onClick={() => accept.mutate(invitation.id)}
                loading={accept.isPending}
              >
                Accept
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  )
}

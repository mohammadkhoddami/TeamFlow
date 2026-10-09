import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MailPlus, UserPlus, X } from 'lucide-react'
import { useState } from 'react'

import { useOrg } from '../components/OrgLayout'
import {
  Avatar,
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageSpinner,
  Select,
} from '../components/ui'
import { useAuth } from '../contexts/auth'
import { useToast } from '../contexts/toast'
import { ApiError, invitationsApi, membersApi } from '../lib/api'
import { qk, useOrgInvitations, useRoles } from '../lib/hooks'
import { useI18n } from '../lib/i18n'
import { ROLE_LABELS, ROLE_RANK, isAdmin, roleRank, type MembershipRole } from '../lib/types'
import { formatDate } from '../lib/utils'

const ALL_ROLES: MembershipRole[] = ['member', 'manager', 'admin', 'owner']

export function MembersPage() {
  const { org, role, members, membersLoading } = useOrg()
  const { user } = useAuth()
  const { t } = useI18n()
  const toast = useToast()
  const queryClient = useQueryClient()
  const invitations = useOrgInvitations(org.slug)
  const roles = useRoles(org.slug, isAdmin(role))

  const [inviteOpen, setInviteOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<MembershipRole>('member')
  const [directAdd, setDirectAdd] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const invalidateMembers = () => {
    void queryClient.invalidateQueries({ queryKey: qk.members(org.slug) })
    void queryClient.invalidateQueries({ queryKey: qk.invitationsOrg(org.slug) })
    void queryClient.invalidateQueries({ queryKey: qk.dashboard(org.slug) })
  }

  const invite = useMutation({
    mutationFn: async (): Promise<unknown> =>
      directAdd
        ? membersApi.add(org.slug, { user_email: email.trim(), role: inviteRole })
        : invitationsApi.create(org.slug, { email: email.trim(), role: inviteRole }),
    onSuccess: () => {
      invalidateMembers()
      setInviteOpen(false)
      setEmail('')
      setError(null)
      toast.success(
        directAdd
          ? t('members.added', 'Member added')
          : t('members.invitationSent', 'Invitation sent'),
      )
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : t('members.inviteError', 'Could not invite member')),
  })

  const changeRole = useMutation({
    mutationFn: ({
      userId,
      data,
    }: {
      userId: string
      data: { role?: string; custom_role_id?: string | null }
    }) => membersApi.updateRole(org.slug, userId, data),
    onSuccess: () => {
      invalidateMembers()
      toast.success(t('members.roleUpdated', 'Role updated'))
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : t('members.roleError', 'Could not update role')),
  })

  const removeMember = useMutation({
    mutationFn: (userId: string) => membersApi.remove(org.slug, userId),
    onSuccess: () => {
      invalidateMembers()
      toast.success(t('members.removed', 'Member removed'))
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : t('members.removeError', 'Could not remove member')),
  })

  const revoke = useMutation({
    mutationFn: (invitationId: string) => invitationsApi.revoke(org.slug, invitationId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.invitationsOrg(org.slug) })
      toast.success(t('members.revoked', 'Invitation revoked'))
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : t('members.revokeError', 'Could not revoke')),
  })

  const pending = invitations.data?.filter((invitation) => invitation.status === 'pending') ?? []

  function assignableRoles(actorRole: string): MembershipRole[] {
    return ALL_ROLES.filter((entry) => entry !== 'owner' && roleRank(entry) < roleRank(actorRole))
  }

  function inviteableRoles(actorRole: string): MembershipRole[] {
    return ALL_ROLES.filter(
      (entry) => entry !== 'owner' && (entry !== 'admin' || isAdmin(actorRole)),
    )
  }

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">{t('members.title', 'Members')}</h1>
          <p className="text-sm text-slate-500">
            {members.length === 1
              ? t('members.countOne', '{count} member in {org}.', {
                  count: members.length,
                  org: org.name,
                })
              : t('members.countMany', '{count} members in {org}.', {
                  count: members.length,
                  org: org.name,
                })}
          </p>
        </div>
        {roleRank(role) >= ROLE_RANK.manager && (
          <Button onClick={() => setInviteOpen(true)}>
            <UserPlus className="h-4 w-4" /> {t('members.invite', 'Invite member')}
          </Button>
        )}
      </div>

      <Card className="overflow-hidden">
        <CardHeader
          title={t('members.team', 'Team')}
          description={t('members.teamHint', 'Roles control what each person can do.')}
        />
        {membersLoading && <PageSpinner />}
        {!membersLoading && members.length === 0 && (
          <EmptyState
            title={t('members.emptyTitle', 'No members yet')}
            description={t('members.emptyBody', 'Invite your teammates to collaborate.')}
          />
        )}
        {members.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2.5 font-medium">{t('members.member', 'Member')}</th>
                  <th className="px-4 py-2.5 font-medium">{t('members.role', 'Role')}</th>
                  <th className="px-4 py-2.5 font-medium">{t('members.joined', 'Joined')}</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody>
                {members.map((membership) => {
                  const isSelf = membership.user_id === user?.id
                  const targetRank = roleRank(membership.role)
                  const canEditRole =
                    !isSelf && membership.role !== 'owner' && roleRank(role) > targetRank
                  const canRemove =
                    membership.role !== 'owner' && (isSelf || roleRank(role) > targetRank)
                  return (
                    <tr key={membership.id} className="border-t border-slate-100">
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2.5">
                          <Avatar
                            name={membership.user?.full_name || membership.user?.email || '?'}
                            email={membership.user?.email}
                          />
                          <div>
                            <p className="font-medium text-slate-800">
                              {membership.user?.full_name || t('common.unnamed', 'Unnamed')}
                              {isSelf && (
                                <span className="ml-1 text-xs text-slate-400">
                                  {t('members.you', '(you)')}
                                </span>
                              )}
                            </p>
                            <p className="text-xs text-slate-500">{membership.user?.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-2.5">
                        {canEditRole ? (
                          <div className="flex flex-wrap items-center gap-2">
                            <Select
                              className="w-auto"
                              value={membership.role}
                              onChange={(event) =>
                                changeRole.mutate({
                                  userId: membership.user_id,
                                  data: { role: event.target.value },
                                })
                              }
                            >
                              {[membership.role, ...assignableRoles(role)]
                                .filter((entry, index, list) => list.indexOf(entry) === index)
                                .map((entry) => (
                                  <option key={entry} value={entry}>
                                    {t(`role.${entry}`, ROLE_LABELS[entry])}
                                  </option>
                                ))}
                            </Select>
                            {(roles.data?.length ?? 0) > 0 && (
                              <Select
                                className="w-auto"
                                title={t('members.customRole', 'Custom role')}
                                value={membership.custom_role_id ?? ''}
                                onChange={(event) =>
                                  changeRole.mutate({
                                    userId: membership.user_id,
                                    data: {
                                      role: membership.role,
                                      custom_role_id: event.target.value || null,
                                    },
                                  })
                                }
                              >
                                <option value="">{t('members.noCustomRole', 'No custom role')}</option>
                                {roles.data?.map((customRole) => (
                                  <option key={customRole.id} value={customRole.id}>
                                    {customRole.name}
                                  </option>
                                ))}
                              </Select>
                            )}
                          </div>
                        ) : (
                          <div className="flex flex-wrap items-center gap-1.5">
                            <Badge
                              className={
                                membership.role === 'owner'
                                  ? 'bg-brand-100 text-brand-700'
                                  : 'bg-slate-100 text-slate-600'
                              }
                            >
                              {t(
                                `role.${membership.role}`,
                                ROLE_LABELS[membership.role] ?? membership.role,
                              )}
                            </Badge>
                            {membership.custom_role_name && (
                              <Badge className="bg-violet-100 text-violet-700">
                                {membership.custom_role_name}
                              </Badge>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-slate-500">
                        {formatDate(membership.created_at)}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {canRemove && (
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => removeMember.mutate(membership.user_id)}
                            className="text-red-600 hover:bg-red-50"
                          >
                            {isSelf ? t('members.leave', 'Leave') : t('common.remove', 'Remove')}
                          </Button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {pending.length > 0 && (
        <Card>
          <CardHeader
            title={t('members.pendingTitle', 'Pending invitations')}
            description={t(
              'members.pendingHint',
              "Invitations that haven't been accepted yet.",
            )}
          />
          <ul>
            {pending.map((invitation) => (
              <li
                key={invitation.id}
                className="flex items-center gap-3 border-t border-slate-100 px-4 py-2.5 first:border-0"
              >
                <MailPlus className="h-4 w-4 text-slate-400" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-700">{invitation.email}</p>
                  <p className="text-xs text-slate-400">
                    {t('members.invited', '{role} · invited {date}', {
                      role: t(`role.${invitation.role}`, ROLE_LABELS[invitation.role]),
                      date: formatDate(invitation.created_at),
                    })}
                  </p>
                </div>
                {roleRank(role) >= ROLE_RANK.manager && (
                  <button
                    className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                    onClick={() => revoke.mutate(invitation.id)}
                    title={t('members.revoke', 'Revoke invitation')}
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Modal
        open={inviteOpen}
        onClose={() => setInviteOpen(false)}
        title={t('members.inviteTitle', 'Invite a member')}
        description={
          directAdd
            ? t('members.inviteDirectHint', 'Adds an existing user to this workspace immediately.')
            : t(
                'members.inviteEmailHint',
                'They will see the invitation in their inbox and can accept or decline.',
              )
        }
        footer={
          <>
            <Button variant="secondary" onClick={() => setInviteOpen(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              onClick={() => invite.mutate()}
              loading={invite.isPending}
              disabled={!email.trim()}
            >
              {directAdd
                ? t('members.addMember', 'Add member')
                : t('members.sendInvitation', 'Send invitation')}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {error && <ErrorState message={error} />}
          <Field label={t('auth.email', 'Email')}>
            <Input
              type="email"
              autoFocus
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder={t('members.emailPlaceholder', 'teammate@company.com')}
            />
          </Field>
          <Field label={t('members.role', 'Role')}>
            <Select
              value={inviteRole}
              onChange={(event) => setInviteRole(event.target.value as MembershipRole)}
            >
              {inviteableRoles(role).map((entry) => (
                <option key={entry} value={entry}>
                  {t(`role.${entry}`, ROLE_LABELS[entry])}
                </option>
              ))}
            </Select>
          </Field>
          {isAdmin(role) && (
            <label className="flex items-center gap-2 text-sm text-slate-600">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-300"
                checked={directAdd}
                onChange={(event) => setDirectAdd(event.target.checked)}
              />
              {t('members.directAdd', 'Add directly (user must already have an account)')}
            </label>
          )}
        </div>
      </Modal>
    </div>
  )
}

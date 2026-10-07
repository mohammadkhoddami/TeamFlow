import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useToast } from '../contexts/toast'
import { ApiError, projectMembersApi } from '../lib/api'
import { qk, useProjectMembers } from '../lib/hooks'
import {
  PROJECT_MEMBER_ROLE_LABELS,
  type ProjectMemberRead,
  type ProjectMemberRole,
} from '../lib/types'
import { Avatar, Button, ErrorState, Field, Input, Modal, Select } from './ui'

const ROLES: ProjectMemberRole[] = ['viewer', 'member', 'manager']

export function ProjectMembersModal({
  projectId,
  open,
  onClose,
}: {
  projectId: string
  open: boolean
  onClose: () => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const members = useProjectMembers(projectId, open)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<ProjectMemberRole>('member')
  const [error, setError] = useState<string | null>(null)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.projectMembers(projectId) })
    void queryClient.invalidateQueries({ queryKey: qk.project(projectId) })
  }

  const add = useMutation({
    mutationFn: () =>
      projectMembersApi.add(projectId, { user_email: email.trim(), role }),
    onSuccess: () => {
      invalidate()
      setEmail('')
      setRole('member')
      setError(null)
      toast.success('Project member added')
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not add member'),
  })

  const changeRole = useMutation({
    mutationFn: ({ member, nextRole }: { member: ProjectMemberRead; nextRole: ProjectMemberRole }) =>
      projectMembersApi.update(projectId, member.user_id, nextRole),
    onSuccess: () => {
      invalidate()
      toast.success('Project role updated')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not update role'),
  })

  const remove = useMutation({
    mutationFn: (member: ProjectMemberRead) =>
      projectMembersApi.remove(projectId, member.user_id),
    onSuccess: () => {
      invalidate()
      toast.success('Project member removed')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not remove member'),
  })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Project members"
      description="Only listed members can access a private project."
      size="lg"
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-48 flex-1">
            <Field label="Email">
              <Input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="teammate@company.com"
              />
            </Field>
          </div>
          <div className="w-36">
            <Field label="Role">
              <Select
                value={role}
                onChange={(event) => setRole(event.target.value as ProjectMemberRole)}
              >
                {ROLES.map((entry) => (
                  <option key={entry} value={entry}>
                    {PROJECT_MEMBER_ROLE_LABELS[entry]}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <Button
            onClick={() => add.mutate()}
            loading={add.isPending}
            disabled={!email.trim()}
          >
            Add
          </Button>
        </div>

        {error && <ErrorState message={error} />}

        {members.isLoading && <p className="text-sm text-slate-400">Loading members…</p>}
        {(members.data?.length ?? 0) === 0 && !members.isLoading && (
          <p className="text-sm text-slate-400">
            No explicit members — the project follows workspace visibility.
          </p>
        )}
        <ul className="space-y-2">
          {members.data?.map((member) => (
            <li
              key={member.id}
              className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 px-3 py-2"
            >
              <Avatar
                name={member.user?.full_name || member.user?.email || '?'}
                email={member.user?.email}
                size="sm"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-800">
                  {member.user?.full_name || 'Unnamed'}
                </p>
                <p className="truncate text-xs text-slate-500">{member.user?.email}</p>
              </div>
              <Select
                className="w-32"
                value={member.role}
                onChange={(event) =>
                  changeRole.mutate({
                    member,
                    nextRole: event.target.value as ProjectMemberRole,
                  })
                }
              >
                {ROLES.map((entry) => (
                  <option key={entry} value={entry}>
                    {PROJECT_MEMBER_ROLE_LABELS[entry]}
                  </option>
                ))}
              </Select>
              <button
                className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                title="Remove"
                onClick={() => remove.mutate(member)}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </Modal>
  )
}

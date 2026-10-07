import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useOrg } from '../OrgLayout'
import { useToast } from '../../contexts/toast'
import { ApiError, rolesApi } from '../../lib/api'
import { qk, useRoles } from '../../lib/hooks'
import { useI18n } from '../../lib/i18n'
import {
  PERMISSION_KEYS,
  PERMISSION_LABELS,
  type CustomRoleRead,
} from '../../lib/types'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  Checkbox,
  ConfirmDialog,
  Field,
  Input,
  Modal,
  Textarea,
} from '../ui'

interface RoleForm {
  name: string
  description: string
  permissions: string[]
}

const EMPTY_FORM: RoleForm = { name: '', description: '', permissions: [] }

export function RolesSection() {
  const { org } = useOrg()
  const toast = useToast()
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const roles = useRoles(org.slug)
  const [editing, setEditing] = useState<CustomRoleRead | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [form, setForm] = useState<RoleForm>(EMPTY_FORM)
  const [deleting, setDeleting] = useState<CustomRoleRead | null>(null)
  const [error, setError] = useState<string | null>(null)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.roles(org.slug) })
    void queryClient.invalidateQueries({ queryKey: qk.members(org.slug) })
  }

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        permissions: form.permissions,
      }
      return editing
        ? rolesApi.update(org.slug, editing.id, payload)
        : rolesApi.create(org.slug, payload)
    },
    onSuccess: () => {
      invalidate()
      setFormOpen(false)
      setEditing(null)
      setError(null)
      toast.success(editing ? 'Role updated' : 'Role created')
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Could not save role'),
  })

  const remove = useMutation({
    mutationFn: (role: CustomRoleRead) => rolesApi.remove(org.slug, role.id),
    onSuccess: () => {
      invalidate()
      setDeleting(null)
      toast.success('Role deleted')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not delete role'),
  })

  function openCreate() {
    setEditing(null)
    setForm(EMPTY_FORM)
    setError(null)
    setFormOpen(true)
  }

  function openEdit(role: CustomRoleRead) {
    setEditing(role)
    setForm({
      name: role.name,
      description: role.description ?? '',
      permissions: role.permissions,
    })
    setError(null)
    setFormOpen(true)
  }

  return (
    <Card>
      <CardHeader
        title={t('settings.roles', 'Custom roles')}
        description="Fine-grained permission bundles you can assign to members."
        action={
          <Button size="sm" variant="secondary" onClick={openCreate}>
            <Plus className="h-3.5 w-3.5" /> New role
          </Button>
        }
      />
      <div className="space-y-3 p-5">
        {(roles.data?.length ?? 0) === 0 && (
          <p className="text-sm text-slate-400">No custom roles yet.</p>
        )}
        {roles.data?.map((role) => (
          <div
            key={role.id}
            className="flex flex-wrap items-start gap-3 rounded-lg border border-slate-200 px-3 py-2"
          >
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-800">{role.name}</p>
              {role.description && (
                <p className="text-xs text-slate-500">{role.description}</p>
              )}
              <div className="mt-1 flex flex-wrap gap-1">
                {role.permissions.map((permission) => (
                  <Badge key={permission}>
                    {PERMISSION_LABELS[permission as keyof typeof PERMISSION_LABELS] ??
                      permission}
                  </Badge>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-1">
              <Button size="sm" variant="ghost" onClick={() => openEdit(role)}>
                <Pencil className="h-3.5 w-3.5" />
              </Button>
              <button
                className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                title="Delete role"
                onClick={() => setDeleting(role)}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>
        ))}
      </div>

      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editing ? 'Edit custom role' : 'New custom role'}
        footer={
          <>
            <Button variant="secondary" onClick={() => setFormOpen(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              onClick={() => save.mutate()}
              loading={save.isPending}
              disabled={!form.name.trim()}
            >
              {t('common.save', 'Save')}
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {error && <p className="text-xs text-red-600">{error}</p>}
          <Field label="Name">
            <Input
              autoFocus
              value={form.name}
              maxLength={64}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
          </Field>
          <Field label="Description">
            <Textarea
              value={form.description}
              maxLength={1000}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
            />
          </Field>
          <div className="space-y-1.5">
            <p className="text-sm font-medium text-slate-700">Permissions</p>
            {PERMISSION_KEYS.map((permission) => (
              <Checkbox
                key={permission}
                label={PERMISSION_LABELS[permission]}
                checked={form.permissions.includes(permission)}
                onChange={(event) =>
                  setForm({
                    ...form,
                    permissions: event.target.checked
                      ? [...form.permissions, permission]
                      : form.permissions.filter((entry) => entry !== permission),
                  })
                }
              />
            ))}
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title="Delete custom role"
        message={`Delete "${deleting?.name ?? ''}"? Members keeping it lose its permissions.`}
        busy={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </Card>
  )
}

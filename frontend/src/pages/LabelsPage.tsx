import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Tags, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useOrg } from '../components/OrgLayout'
import {
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageSpinner,
} from '../components/ui'
import { useToast } from '../contexts/toast'
import { ApiError, labelsApi } from '../lib/api'
import { qk, useLabels } from '../lib/hooks'
import { useI18n } from '../lib/i18n'
import { canManage, type LabelRead } from '../lib/types'

export function LabelsPage() {
  const { org, role } = useOrg()
  const labels = useLabels(org.slug)
  const queryClient = useQueryClient()
  const { t } = useI18n()
  const toast = useToast()

  const [editing, setEditing] = useState<LabelRead | null>(null)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [color, setColor] = useState('#6366f1')
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<LabelRead | null>(null)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.labels(org.slug) })
  }

  const save = useMutation({
    mutationFn: () =>
      editing
        ? labelsApi.update(editing.id, { name: name.trim(), color })
        : labelsApi.create(org.slug, { name: name.trim(), color }),
    onSuccess: () => {
      invalidate()
      setOpen(false)
      setEditing(null)
      setError(null)
      toast.success(
        editing ? t('labels.updated', 'Label updated') : t('labels.created', 'Label created'),
      )
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : t('labels.saveError', 'Could not save label')),
  })

  const remove = useMutation({
    mutationFn: (labelId: string) => labelsApi.remove(labelId),
    onSuccess: () => {
      invalidate()
      setDeleting(null)
      toast.success(t('labels.deleted', 'Label deleted'))
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : t('labels.deleteError', 'Could not delete label')),
  })

  function openCreate() {
    setEditing(null)
    setName('')
    setColor('#6366f1')
    setError(null)
    setOpen(true)
  }

  function openEdit(label: LabelRead) {
    setEditing(label)
    setName(label.name)
    setColor(label.color ?? '#6366f1')
    setError(null)
    setOpen(true)
  }

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">{t('labels.title', 'Labels')}</h1>
          <p className="text-sm text-slate-500">
            {t('labels.subtitle', 'Categorize tasks across every project.')}
          </p>
        </div>
        {canManage(role) && (
          <Button onClick={openCreate}>
            <Plus className="h-4 w-4" /> {t('labels.new', 'New label')}
          </Button>
        )}
      </div>

      {labels.isLoading && <PageSpinner />}
      {labels.isError && (
        <ErrorState
          message={t('labels.loadError', 'Could not load labels.')}
          onRetry={() => void labels.refetch()}
        />
      )}

      {labels.data?.length === 0 && (
        <EmptyState
          icon={<Tags className="h-8 w-8" />}
          title={t('labels.emptyTitle', 'No labels yet')}
          description={
            canManage(role)
              ? t(
                  'labels.emptyManage',
                  'Create labels like "bug", "design" or "customer" to organize tasks.',
                )
              : t('labels.emptyMember', 'Managers can create labels for this workspace.')
          }
        />
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {labels.data?.map((label) => (
          <Card key={label.id} className="flex items-center gap-3 p-4">
            <span
              className="h-8 w-8 shrink-0 rounded-lg"
              style={{ backgroundColor: label.color ?? '#94a3b8' }}
            />
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium text-slate-800">{label.name}</p>
              <p className="text-xs text-slate-400">{label.color ?? t('labels.noColor', 'no color')}</p>
            </div>
            {canManage(role) && (
              <div className="flex items-center gap-1">
                <button
                  className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                  onClick={() => openEdit(label)}
                  title={t('labels.editTitle', 'Edit label')}
                >
                  <Pencil className="h-4 w-4" />
                </button>
                <button
                  className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                  onClick={() => setDeleting(label)}
                  title={t('labels.deleteTitle', 'Delete label')}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            )}
          </Card>
        ))}
      </div>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={editing ? t('labels.editTitle', 'Edit label') : t('labels.new', 'New label')}
        size="sm"
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              onClick={() => save.mutate()}
              loading={save.isPending}
              disabled={!name.trim()}
            >
              {editing ? t('common.save', 'Save') : t('common.create', 'Create')}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {error && <ErrorState message={error} />}
          <Field label={t('common.name', 'Name')}>
            <Input
              autoFocus
              value={name}
              maxLength={64}
              onChange={(event) => setName(event.target.value)}
              placeholder={t('labels.namePlaceholder', 'bug')}
            />
          </Field>
          <Field label={t('labels.color', 'Color')}>
            <div className="flex items-center gap-3">
              <input
                type="color"
                value={color}
                onChange={(event) => setColor(event.target.value)}
                className="h-9 w-14 cursor-pointer rounded border border-slate-300 bg-white p-1"
              />
              <span className="font-mono text-xs text-slate-500">{color}</span>
            </div>
          </Field>
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title={t('labels.deleteTitle', 'Delete label')}
        message={t(
          'labels.deleteMessage',
          'Delete "{name}"? It will be removed from all tasks.',
          { name: deleting?.name ?? '' },
        )}
        busy={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  )
}

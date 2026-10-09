import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ClipboardCopy, Eye, FileText, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useOrg } from './OrgLayout'
import {
  Badge,
  Button,
  Card,
  ConfirmDialog,
  Drawer,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageSpinner,
  Select,
  Textarea,
} from './ui'
import { useToast } from '../contexts/toast'
import { ApiError, formsApi } from '../lib/api'
import { qk, useForms, useFormSubmissions } from '../lib/hooks'
import { useI18n } from '../lib/i18n'
import {
  FORM_FIELD_TYPES,
  FORM_FIELD_TYPE_LABELS,
  type FormField,
  type FormFieldType,
  type FormRead,
} from '../lib/types'
import { canManage } from '../lib/types'
import { formatDateTime } from '../lib/utils'

interface EditableField {
  key: string
  label: string
  type: FormFieldType
  required: boolean
  options: string
}

interface FormState {
  name: string
  description: string
  isPublic: boolean
  fields: EditableField[]
}

const EMPTY_FORM: FormState = {
  name: '',
  description: '',
  isPublic: true,
  fields: [],
}

function slugify(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 64)
  return slug || 'field'
}

export function FormsManager({ projectId }: { projectId: string }) {
  const { role } = useOrg()
  const { t } = useI18n()
  const toast = useToast()
  const queryClient = useQueryClient()
  const forms = useForms(projectId)
  const manager = canManage(role)

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<FormRead | null>(null)
  const [state, setState] = useState<FormState>(EMPTY_FORM)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<FormRead | null>(null)
  const [submissionsFor, setSubmissionsFor] = useState<FormRead | null>(null)
  const submissions = useFormSubmissions(projectId, submissionsFor?.id ?? null)

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: qk.forms(projectId) })

  const save = useMutation({
    mutationFn: () => {
      const fields: FormField[] = state.fields.map((field) => ({
        key: field.key.trim() || slugify(field.label),
        label: field.label.trim(),
        type: field.type,
        required: field.required,
        options:
          field.type === 'select'
            ? field.options
                .split(',')
                .map((option) => option.trim())
                .filter(Boolean)
            : [],
      }))
      const payload = {
        name: state.name.trim(),
        description: state.description.trim() || null,
        fields,
        is_public: state.isPublic,
      }
      return editing
        ? formsApi.update(projectId, editing.id, payload)
        : formsApi.create(projectId, payload)
    },
    onSuccess: () => {
      invalidate()
      setFormOpen(false)
      setEditing(null)
      setError(null)
      toast.success(
        editing ? t('forms.updated', 'Form updated') : t('forms.created', 'Form created'),
      )
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : t('forms.saveError', 'Could not save form')),
  })

  const remove = useMutation({
    mutationFn: (form: FormRead) => formsApi.remove(projectId, form.id),
    onSuccess: () => {
      invalidate()
      setDeleting(null)
      toast.success(t('forms.deleted', 'Form deleted'))
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : t('forms.deleteError', 'Could not delete form')),
  })

  function openCreate() {
    setEditing(null)
    setState(EMPTY_FORM)
    setError(null)
    setFormOpen(true)
  }

  function openEdit(form: FormRead) {
    setEditing(form)
    setState({
      name: form.name,
      description: form.description ?? '',
      isPublic: form.is_public,
      fields: form.fields.map((field) => ({
        key: field.key,
        label: field.label,
        type: field.type,
        required: field.required,
        options: field.options.join(', '),
      })),
    })
    setError(null)
    setFormOpen(true)
  }

  function updateField(index: number, patch: Partial<EditableField>) {
    setState((previous) => ({
      ...previous,
      fields: previous.fields.map((field, fieldIndex) =>
        fieldIndex === index ? { ...field, ...patch } : field,
      ),
    }))
  }

  function publicUrl(form: FormRead): string {
    return `${window.location.origin}${import.meta.env.BASE_URL}forms/${form.slug}`
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">{t('forms.title', 'Intake forms')}</h2>
          <p className="text-xs text-slate-500">
            {t(
              'forms.subtitle',
              'Public forms create tasks in this project from anonymous submissions.',
            )}
          </p>
        </div>
        {manager && (
          <Button size="sm" onClick={openCreate}>
            <Plus className="h-3.5 w-3.5" /> {t('forms.new', 'New form')}
          </Button>
        )}
      </div>

      {forms.isLoading && <PageSpinner label={t('forms.loading', 'Loading forms…')} />}
      {forms.isError && (
        <ErrorState
          message={t('forms.loadError', 'Could not load forms.')}
          onRetry={() => void forms.refetch()}
        />
      )}
      {forms.data?.length === 0 && (
        <EmptyState
          icon={<FileText className="h-8 w-8" />}
          title={t('forms.empty.title', 'No forms yet')}
          description={t(
            'forms.empty.description',
            'Create a form to collect requests from people outside the workspace.',
          )}
        />
      )}

      <div className="space-y-3">
        {forms.data?.map((form) => (
          <Card key={form.id} className="flex flex-wrap items-center gap-3 p-4">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-800">
                {form.name}
                {!form.is_public && (
                  <Badge className="ml-2">{t('forms.badgePrivate', 'private')}</Badge>
                )}
              </p>
              <p className="text-xs text-slate-500">
                {t('forms.meta', '{fields} · {submissions} ·', {
                  fields:
                    form.fields.length === 1
                      ? t('forms.fieldOne', '1 field')
                      : t('forms.fieldMany', '{count} fields', { count: form.fields.length }),
                  submissions:
                    form.submit_count === 1
                      ? t('forms.submissionOne', '1 submission')
                      : t('forms.submissionMany', '{count} submissions', {
                          count: form.submit_count,
                        }),
                })}{' '}
                <code className="rounded bg-slate-100 px-1">/forms/{form.slug}</code>
              </p>
            </div>
            <div className="flex items-center gap-1">
              <Button
                size="sm"
                variant="ghost"
                title={t('forms.copyLinkHint', 'Copy public link')}
                onClick={() => {
                  void navigator.clipboard.writeText(publicUrl(form)).then(
                    () => toast.success(t('forms.linkCopied', 'Public link copied')),
                    () => toast.error(t('forms.copyLinkError', 'Could not copy link')),
                  )
                }}
              >
                <ClipboardCopy className="h-3.5 w-3.5" /> {t('forms.link', 'Link')}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                title={t('forms.viewSubmissions', 'View submissions')}
                onClick={() => setSubmissionsFor(form)}
              >
                <Eye className="h-3.5 w-3.5" /> {t('forms.submissions', 'Submissions')}
              </Button>
              {manager && (
                <>
                  <Button size="sm" variant="secondary" onClick={() => openEdit(form)}>
                    {t('common.edit', 'Edit')}
                  </Button>
                  <button
                    className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                    title={t('forms.deleteTitle', 'Delete form')}
                    onClick={() => setDeleting(form)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </>
              )}
            </div>
          </Card>
        ))}
      </div>

      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editing ? t('forms.edit', 'Edit form') : t('forms.new', 'New form')}
        size="lg"
        footer={
          <>
            <Button variant="secondary" onClick={() => setFormOpen(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button
              onClick={() => save.mutate()}
              loading={save.isPending}
              disabled={!state.name.trim()}
            >
              {t('forms.save', 'Save form')}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {error && <ErrorState message={error} />}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('common.name', 'Name')}>
              <Input
                autoFocus
                value={state.name}
                maxLength={128}
                onChange={(event) => setState({ ...state, name: event.target.value })}
              />
            </Field>
            <Field label={t('forms.visibility', 'Visibility')}>
              <Select
                value={state.isPublic ? 'public' : 'private'}
                onChange={(event) =>
                  setState({ ...state, isPublic: event.target.value === 'public' })
                }
              >
                <option value="public">{t('forms.publicLink', 'Public link')}</option>
                <option value="private">{t('forms.private', 'Private')}</option>
              </Select>
            </Field>
          </div>
          <Field label={t('common.description', 'Description')}>
            <Textarea
              value={state.description}
              maxLength={20_000}
              onChange={(event) => setState({ ...state, description: event.target.value })}
            />
          </Field>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium text-slate-700">{t('forms.fields', 'Fields')}</p>
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  setState({
                    ...state,
                    fields: [
                      ...state.fields,
                      { key: '', label: '', type: 'text', required: false, options: '' },
                    ],
                  })
                }
              >
                <Plus className="h-3.5 w-3.5" /> {t('forms.addField', 'Add field')}
              </Button>
            </div>
            {state.fields.length === 0 && (
              <p className="text-xs text-slate-400">{t('forms.noFields', 'No fields yet.')}</p>
            )}
            {state.fields.map((field, index) => (
              <div
                key={index}
                className="space-y-2 rounded-lg border border-slate-200 p-3"
              >
                <div className="grid gap-2 sm:grid-cols-2">
                  <Field label={t('forms.fieldLabel', 'Label')}>
                    <Input
                      value={field.label}
                      maxLength={256}
                      onChange={(event) =>
                        updateField(index, {
                          label: event.target.value,
                          key: field.key || slugify(event.target.value),
                        })
                      }
                    />
                  </Field>
                  <Field
                    label={t('forms.fieldKey', 'Key')}
                    hint={t('forms.fieldKeyHint', 'Identifier sent with the submission')}
                  >
                    <Input
                      value={field.key}
                      maxLength={64}
                      onChange={(event) => updateField(index, { key: event.target.value })}
                    />
                  </Field>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <Field label={t('common.type', 'Type')}>
                    <Select
                      value={field.type}
                      onChange={(event) =>
                        updateField(index, { type: event.target.value as FormFieldType })
                      }
                    >
                      {FORM_FIELD_TYPES.map((type) => (
                        <option key={type} value={type}>
                          {t(`formFieldType.${type}`, FORM_FIELD_TYPE_LABELS[type])}
                        </option>
                      ))}
                    </Select>
                  </Field>
                  {field.type === 'select' && (
                    <Field
                      label={t('forms.options', 'Options')}
                      hint={t('forms.optionsHint', 'Comma separated')}
                    >
                      <Input
                        value={field.options}
                        onChange={(event) => updateField(index, { options: event.target.value })}
                      />
                    </Field>
                  )}
                </div>
                <div className="flex items-center justify-between">
                  <label className="flex items-center gap-2 text-sm text-slate-600">
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-slate-300"
                      checked={field.required}
                      onChange={(event) =>
                        updateField(index, { required: event.target.checked })
                      }
                    />
                    {t('common.required', 'Required')}
                  </label>
                  <button
                    className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                    title={t('forms.removeField', 'Remove field')}
                    onClick={() =>
                      setState({
                        ...state,
                        fields: state.fields.filter((_, fieldIndex) => fieldIndex !== index),
                      })
                    }
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </Modal>

      <Drawer
        open={Boolean(submissionsFor)}
        onClose={() => setSubmissionsFor(null)}
        title={
          <div>
            <p className="text-sm font-semibold text-slate-900">
              {t('forms.submissionsTitle', 'Submissions — {name}', {
                name: submissionsFor?.name ?? '',
              })}
            </p>
            <p className="text-xs text-slate-500">{t('forms.newestFirst', 'Newest first.')}</p>
          </div>
        }
      >
        <div className="space-y-3 p-4">
          {submissions.isLoading && (
            <PageSpinner label={t('forms.loadingSubmissions', 'Loading submissions…')} />
          )}
          {submissions.isError && (
            <ErrorState
              message={t('forms.submissionsError', 'Could not load submissions.')}
              onRetry={() => void submissions.refetch()}
            />
          )}
          {(submissions.data?.length ?? 0) === 0 && !submissions.isLoading && (
            <p className="text-sm text-slate-400">
              {t('forms.noSubmissions', 'No submissions yet.')}
            </p>
          )}
          {submissions.data?.map((submission) => (
            <Card key={submission.id} className="p-3">
              <p className="text-xs text-slate-400">
                {formatDateTime(submission.created_at)}
                {submission.task_id
                  ? t('forms.linkedTask', ' · task {id}', {
                      id: submission.task_id.slice(0, 8),
                    })
                  : ''}
              </p>
              <dl className="mt-2 space-y-1">
                {Object.entries(submission.data).map(([key, value]) => (
                  <div key={key} className="flex gap-2 text-sm">
                    <dt className="w-32 shrink-0 truncate text-slate-500">{key}</dt>
                    <dd className="min-w-0 flex-1 break-words text-slate-800">
                      {String(value)}
                    </dd>
                  </div>
                ))}
              </dl>
            </Card>
          ))}
        </div>
      </Drawer>

      <ConfirmDialog
        open={Boolean(deleting)}
        title={t('forms.deleteTitle', 'Delete form')}
        message={t(
          'forms.deleteConfirm',
          'Delete "{name}"? The public link stops working immediately.',
          { name: deleting?.name ?? '' },
        )}
        busy={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </div>
  )
}

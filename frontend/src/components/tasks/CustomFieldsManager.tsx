import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useToast } from '../../contexts/toast'
import { ApiError, customFieldsApi } from '../../lib/api'
import { qk, useCustomFields } from '../../lib/hooks'
import type { CustomFieldType } from '../../lib/types'
import { Button, Checkbox, Field, Input, Modal, Select } from '../ui'

const FIELD_TYPES: { value: CustomFieldType; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'number', label: 'Number' },
  { value: 'date', label: 'Date' },
  { value: 'select', label: 'Select' },
  { value: 'multi_select', label: 'Multi-select' },
  { value: 'user', label: 'User' },
  { value: 'checkbox', label: 'Checkbox' },
]

export function CustomFieldsManager({
  projectId,
  open,
  onClose,
}: {
  projectId: string
  open: boolean
  onClose: () => void
}) {
  const fields = useCustomFields(projectId)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [name, setName] = useState('')
  const [fieldType, setFieldType] = useState<CustomFieldType>('text')
  const [options, setOptions] = useState('')
  const [required, setRequired] = useState(false)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.customFields(projectId) })
    void queryClient.invalidateQueries({ queryKey: ['orgs'] })
  }

  const create = useMutation({
    mutationFn: () =>
      customFieldsApi.create(projectId, {
        name: name.trim(),
        field_type: fieldType,
        options:
          fieldType === 'select' || fieldType === 'multi_select'
            ? options.split(',').map((entry) => entry.trim()).filter(Boolean)
            : [],
        is_required: required,
      }),
    onSuccess: () => {
      invalidate()
      setName('')
      setOptions('')
      setRequired(false)
      toast.success('Custom field created')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not create field'),
  })

  const remove = useMutation({
    mutationFn: (fieldId: string) => customFieldsApi.remove(projectId, fieldId),
    onSuccess: () => {
      invalidate()
      toast.success('Custom field deleted')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not delete field'),
  })

  return (
    <Modal open={open} onClose={onClose} title="Custom fields" size="lg">
      <div className="space-y-5">
        <section className="space-y-2">
          {(fields.data ?? []).map((field) => (
            <div
              key={field.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2.5"
            >
              <div>
                <p className="text-sm font-medium text-slate-800">
                  {field.name}
                  {field.is_required && (
                    <span className="ml-1 text-[10px] text-red-500">required</span>
                  )}
                </p>
                <p className="text-[11px] text-slate-400">
                  {field.field_type.replace('_', '-')} · key <code>{field.key}</code>
                  {field.options.length > 0 ? ` · ${field.options.join(', ')}` : ''}
                </p>
              </div>
              <button
                type="button"
                onClick={() => remove.mutate(field.id)}
                className="rounded p-1.5 text-slate-300 hover:bg-red-50 hover:text-red-600"
                title="Delete field (values are removed)"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          {(fields.data ?? []).length === 0 && (
            <p className="rounded-lg border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400">
              No custom fields yet. Add typed attributes without schema changes.
            </p>
          )}
        </section>

        <section className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <p className="text-sm font-semibold text-slate-800">New field</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name">
              <Input
                value={name}
                maxLength={64}
                placeholder="Severity"
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Field label="Type">
              <Select
                value={fieldType}
                onChange={(event) => setFieldType(event.target.value as CustomFieldType)}
              >
                {FIELD_TYPES.map((entry) => (
                  <option key={entry.value} value={entry.value}>
                    {entry.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          {(fieldType === 'select' || fieldType === 'multi_select') && (
            <Field label="Options" hint="Comma separated">
              <Input
                value={options}
                placeholder="low, medium, high"
                onChange={(event) => setOptions(event.target.value)}
              />
            </Field>
          )}
          <Checkbox
            label="Required on new tasks"
            checked={required}
            onChange={(event) => setRequired(event.target.checked)}
          />
          <Button
            onClick={() => create.mutate()}
            loading={create.isPending}
            disabled={!name.trim()}
          >
            <Plus className="h-4 w-4" /> Create field
          </Button>
        </section>
      </div>
    </Modal>
  )
}

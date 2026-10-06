import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useToast } from '../../contexts/toast'
import { ApiError, workflowsApi } from '../../lib/api'
import { qk, useWorkflow } from '../../lib/hooks'
import type { TaskCategory, WorkflowStatusInput } from '../../lib/types'
import { Button, Checkbox, Field, Input, Modal, Select } from '../ui'

const CATEGORIES: { value: TaskCategory; label: string }[] = [
  { value: 'todo', label: 'To do' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'in_review', label: 'In review' },
  { value: 'done', label: 'Done' },
]

const slug = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 32) || 'status'

export function WorkflowManager({
  projectId,
  open,
  onClose,
}: {
  projectId: string
  open: boolean
  onClose: () => void
}) {
  const workflow = useWorkflow(projectId)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [statuses, setStatuses] = useState<WorkflowStatusInput[]>([])
  const [wipEnforced, setWipEnforced] = useState(false)

  useEffect(() => {
    if (workflow.data && open) {
      setStatuses(
        workflow.data.map((entry) => ({
          key: entry.key,
          name: entry.name,
          category: entry.category,
          wip_limit: entry.wip_limit,
          transitions: [...entry.transitions],
        })),
      )
    }
  }, [workflow.data, open])

  const save = useMutation({
    mutationFn: () =>
      workflowsApi.save(projectId, { statuses, wip_enforced: wipEnforced }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.workflow(projectId) })
      void queryClient.invalidateQueries({ queryKey: ['orgs'] })
      toast.success('Workflow saved')
      onClose()
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'Could not save the workflow'),
  })

  const update = (index: number, patch: Partial<WorkflowStatusInput>) => {
    setStatuses((current) =>
      current.map((entry, position) =>
        position === index ? { ...entry, ...patch } : entry,
      ),
    )
  }

  const toggleTransition = (index: number, key: string) => {
    setStatuses((current) =>
      current.map((entry, position) => {
        if (position !== index) return entry
        const has = entry.transitions.includes(key)
        return {
          ...entry,
          transitions: has
            ? entry.transitions.filter((value) => value !== key)
            : [...entry.transitions, key],
        }
      }),
    )
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Workflow & WIP limits"
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} loading={save.isPending}>
            Save workflow
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-xs text-slate-500">
          Default is the classic four-column flow. Renaming keys is not supported;
          add new statuses for custom flows. Removing a status re-homes its tasks.
        </p>
        <Checkbox
          label="Enforce WIP limits (reject moves into a full column)"
          checked={wipEnforced}
          onChange={(event) => setWipEnforced(event.target.checked)}
        />

        <div className="space-y-3">
          {statuses.map((entry, index) => (
            <div key={entry.key} className="rounded-lg border border-slate-200 p-3">
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Name">
                  <Input
                    value={entry.name}
                    onChange={(event) => update(index, { name: event.target.value })}
                  />
                </Field>
                <Field label="Key" hint="Immutable once created">
                  <Input
                    value={entry.key}
                    disabled={!entry.key.startsWith('new_')}
                    onChange={(event) =>
                      update(index, { key: slug(event.target.value) })
                    }
                  />
                </Field>
                <Field label="Category">
                  <Select
                    value={entry.category}
                    onChange={(event) =>
                      update(index, { category: event.target.value as TaskCategory })
                    }
                  >
                    {CATEGORIES.map((category) => (
                      <option key={category.value} value={category.value}>
                        {category.label}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="WIP limit" hint="Empty = unlimited">
                  <Input
                    type="number"
                    min={0}
                    value={entry.wip_limit ?? ''}
                    onChange={(event) =>
                      update(index, {
                        wip_limit: event.target.value === '' ? null : Number(event.target.value),
                      })
                    }
                  />
                </Field>
              </div>
              <div className="mt-2">
                <p className="text-[11px] font-medium text-slate-500">Allowed next statuses</p>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {statuses
                    .filter((candidate) => candidate.key !== entry.key)
                    .map((candidate) => (
                      <button
                        key={candidate.key}
                        type="button"
                        onClick={() => toggleTransition(index, candidate.key)}
                        className={
                          entry.transitions.includes(candidate.key)
                            ? 'rounded-full border border-brand-300 bg-brand-50 px-2 py-0.5 text-[11px] text-brand-700'
                            : 'rounded-full border border-slate-200 px-2 py-0.5 text-[11px] text-slate-500 hover:border-slate-300'
                        }
                      >
                        {candidate.name}
                      </button>
                    ))}
                </div>
              </div>
              <div className="mt-2 flex justify-end">
                <button
                  type="button"
                  onClick={() =>
                    setStatuses((current) => current.filter((_e, i) => i !== index))
                  }
                  className="inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-red-600"
                >
                  <Trash2 className="h-3 w-3" /> Remove status
                </button>
              </div>
            </div>
          ))}
        </div>

        <Button
          variant="secondary"
          size="sm"
          onClick={() =>
            setStatuses((current) => [
              ...current,
              {
                key: `new_${current.length + 1}`,
                name: 'New status',
                category: 'in_progress',
                wip_limit: null,
                transitions: [],
              },
            ])
          }
        >
          <Plus className="h-3.5 w-3.5" /> Add status
        </Button>
      </div>
    </Modal>
  )
}

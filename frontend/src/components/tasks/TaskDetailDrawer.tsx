import { useMutation, useQuery } from '@tanstack/react-query'
import { CalendarDays, CornerDownRight, Eye, EyeOff, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useAuth } from '../../contexts/auth'
import { useToast } from '../../contexts/toast'
import { ApiError, tasksApi } from '../../lib/api'
import { qk, useInvalidateTasks, useLabels, useSprints, useTaskChildren } from '../../lib/hooks'
import {
  PRIORITIES,
  PRIORITY_BADGE,
  PRIORITY_LABELS,
  STATUS_BADGE,
  STATUS_LABELS,
  STATUS_TRANSITIONS,
  TASK_TYPES,
  TYPE_BADGE,
  TYPE_LABELS,
  allowedParentTypes,
  type TaskPriority,
  type TaskRead,
  type TaskStatus,
  type TaskType,
} from '../../lib/types'
import { cn, formatDateTime, fromDateTimeLocal, relativeTime, toDateTimeLocal } from '../../lib/utils'
import { useOrg } from '../OrgLayout'
import {
  Avatar,
  Badge,
  Button,
  ConfirmDialog,
  Drawer,
  Field,
  Input,
  Select,
} from '../ui'
import { MarkdownEditor } from '../MarkdownEditor'
import { AttachmentsSection } from './AttachmentsSection'
import { CommentsSection } from './CommentsSection'
import { LabelPicker } from './LabelPicker'

export function TaskDetailDrawer({
  task,
  onClose,
  onOpenTask,
  onAddChild,
}: {
  task: TaskRead | null
  onClose: () => void
  onOpenTask?: (task: TaskRead) => void
  onAddChild?: (task: TaskRead) => void
}) {
  const { org, role, members } = useOrg()
  const { user } = useAuth()
  const labels = useLabels(org.slug)
  const invalidate = useInvalidateTasks()
  const toast = useToast()

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)

  const detail = useQuery({
    queryKey: qk.task(task?.id ?? ''),
    queryFn: () => tasksApi.get(task!.id),
    enabled: Boolean(task),
  })

  const projectTasks = useQuery({
    queryKey: qk.tasks(org.slug, { project_id: detail.data?.project_id ?? '', limit: 100 }),
    queryFn: () => tasksApi.list(org.slug, { project_id: detail.data!.project_id, limit: 100 }),
    enabled: Boolean(detail.data),
  })

  const current = detail.data ?? task
  const children = useTaskChildren(current?.id)
  const sprints = useSprints(current?.project_id)

  useEffect(() => {
    if (current) {
      setTitle(current.title)
      setDescription(current.description ?? '')
      setDueDate(toDateTimeLocal(current.due_date))
    }
  }, [current?.id, current?.title, current?.description, current?.due_date])

  const patch = useMutation({
    mutationFn: (data: Parameters<typeof tasksApi.update>[1]) => tasksApi.update(current!.id, data),
    onSuccess: () => invalidate(org.slug, current!.id),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not update task'),
  })

  const move = useMutation({
    mutationFn: (status: TaskStatus) => tasksApi.move(current!.id, status),
    onSuccess: () => invalidate(org.slug, current!.id),
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'That status change is not allowed'),
  })

  const toggleWatch = useMutation({
    mutationFn: () =>
      watching ? tasksApi.unwatch(current!.id) : tasksApi.watch(current!.id),
    onSuccess: () => invalidate(org.slug, current!.id),
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not update watcher'),
  })

  const remove = useMutation({
    mutationFn: () => tasksApi.remove(current!.id),
    onSuccess: () => {
      invalidate(org.slug)
      toast.success('Task deleted')
      onClose()
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not delete task'),
  })

  if (!task || !current) return null

  const watching = current.watcher_ids.includes(user?.id ?? '')
  const canDelete = role !== 'member' || current.created_by_id === user?.id
  const statusOptions: TaskStatus[] = [current.status, ...STATUS_TRANSITIONS[current.status]]
  const watchers = members.filter((membership) => current.watcher_ids.includes(membership.user_id))
  const titleDirty = title.trim() !== current.title && title.trim().length > 0

  const parentTypes = allowedParentTypes(current.type)
  const parentCandidates = (projectTasks.data?.items ?? []).filter(
    (entry) => entry.id !== current.id && parentTypes.includes(entry.type),
  )

  const changeType = (next: TaskType) => {
    const parentStillValid = current.parent
      ? allowedParentTypes(next).includes(current.parent.type)
      : true
    patch.mutate(
      parentStillValid ? { type: next } : { type: next, parent_id: null },
    )
  }

  const openParent = async () => {
    if (!current.parent || !onOpenTask) return
    try {
      onOpenTask(await tasksApi.get(current.parent.id))
    } catch {
      toast.error('Could not open the parent task')
    }
  }

  return (
    <Drawer
      open
      wide
      onClose={onClose}
      title={
        <div className="min-w-0 pr-2">
          <div className="flex items-center gap-2">
            <Badge className={TYPE_BADGE[current.type]}>{TYPE_LABELS[current.type]}</Badge>
            <Badge className={STATUS_BADGE[current.status]}>{STATUS_LABELS[current.status]}</Badge>
            <Badge className={PRIORITY_BADGE[current.priority]}>
              {PRIORITY_LABELS[current.priority]}
            </Badge>
            {current.key && (
              <span className="font-mono text-[11px] text-slate-400">{current.key}</span>
            )}
            {current.estimate != null && (
              <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                {current.estimate} pts
              </span>
            )}
          </div>
          {current.parent && (
            <button
              type="button"
              onClick={openParent}
              className="mt-1 flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-600"
            >
              <CornerDownRight className="h-3 w-3" />
              {TYPE_LABELS[current.parent.type]} · {current.parent.title}
            </button>
          )}
          <p className="mt-1 truncate text-base font-semibold text-slate-900">{current.title}</p>
        </div>
      }
    >
      <div className="space-y-6 px-5 py-4">
        <div className="flex items-start gap-2">
          <Input
            value={title}
            maxLength={255}
            onChange={(event) => setTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && titleDirty) patch.mutate({ title: title.trim() })
            }}
          />
          {titleDirty && (
            <Button size="sm" onClick={() => patch.mutate({ title: title.trim() })} loading={patch.isPending}>
              Save
            </Button>
          )}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Status">
            <Select
              value={current.status}
              onChange={(event) => move.mutate(event.target.value as TaskStatus)}
            >
              {statusOptions.map((status) => (
                <option key={status} value={status}>
                  {STATUS_LABELS[status]}
                  {status === current.status ? ' (current)' : ''}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Priority">
            <Select
              value={current.priority}
              onChange={(event) =>
                patch.mutate({ priority: event.target.value as TaskPriority })
              }
            >
              {PRIORITIES.map((priority) => (
                <option key={priority} value={priority}>
                  {PRIORITY_LABELS[priority]}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Type" hint={current.child_count > 0 ? 'Has children — keep the level lower than theirs' : undefined}>
            <Select value={current.type} onChange={(event) => changeType(event.target.value as TaskType)}>
              {TASK_TYPES.map((value) => (
                <option key={value} value={value}>
                  {TYPE_LABELS[value]}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Parent"
            hint={parentTypes.length === 0 ? 'Epics are always top level' : undefined}
          >
            <Select
              value={current.parent_id ?? ''}
              disabled={parentTypes.length === 0}
              onChange={(event) => patch.mutate({ parent_id: event.target.value || null })}
            >
              <option value="">No parent (top level)</option>
              {parentCandidates.map((parent) => (
                <option key={parent.id} value={parent.id}>
                  [{TYPE_LABELS[parent.type]}] {parent.title}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Assignee">
            <Select
              value={current.assignee_id ?? ''}
              onChange={(event) => patch.mutate({ assignee_id: event.target.value || null })}
            >
              <option value="">Unassigned</option>
              {members.map((membership) => (
                <option key={membership.user_id} value={membership.user_id}>
                  {membership.user?.full_name || membership.user?.email || membership.user_id}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Due date">
            <Input
              type="datetime-local"
              value={dueDate}
              onChange={(event) => setDueDate(event.target.value)}
              onBlur={() => {
                const next = fromDateTimeLocal(dueDate)
                const before = current.due_date ? new Date(current.due_date).toISOString() : null
                if (next !== before) patch.mutate({ due_date: next })
              }}
            />
          </Field>
          <Field label="Sprint">
            <Select
              value={current.sprint_id ?? ''}
              onChange={(event) => patch.mutate({ sprint_id: event.target.value || null })}
            >
              <option value="">Backlog (no sprint)</option>
              {(sprints.data ?? [])
                .filter(
                  (sprint) =>
                    sprint.state !== 'completed' || sprint.id === current.sprint_id,
                )
                .map((sprint) => (
                  <option key={sprint.id} value={sprint.id}>
                    {sprint.name}
                    {sprint.state === 'active' ? ' (active)' : ''}
                    {sprint.state === 'completed' ? ' (completed)' : ''}
                  </option>
                ))}
            </Select>
          </Field>
          <Field label="Estimate" hint="Points or hours per project setting">
            <Input
              type="number"
              min={0}
              step="0.5"
              defaultValue={current.estimate ?? ''}
              key={`estimate-${current.id}-${current.estimate}`}
              onBlur={(event) => {
                const raw = event.target.value.trim()
                const next = raw === '' ? null : Number(raw)
                if (next !== current.estimate) patch.mutate({ estimate: next })
              }}
            />
          </Field>
          <Field label="Remaining">
            <Input
              type="number"
              min={0}
              step="0.5"
              defaultValue={current.remaining_estimate ?? ''}
              key={`remaining-${current.id}-${current.remaining_estimate}`}
              onBlur={(event) => {
                const raw = event.target.value.trim()
                const next = raw === '' ? null : Number(raw)
                if (next !== current.remaining_estimate) {
                  patch.mutate({ remaining_estimate: next })
                }
              }}
            />
          </Field>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2.5">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-500">Watchers</span>
            <div className="flex -space-x-1.5">
              {watchers.slice(0, 5).map((membership) => (
                <Avatar
                  key={membership.user_id}
                  name={membership.user?.full_name || membership.user?.email || '?'}
                  email={membership.user?.email}
                  size="sm"
                />
              ))}
              {watchers.length === 0 && <span className="text-xs text-slate-400">none</span>}
            </div>
          </div>
          <Button
            size="sm"
            variant={watching ? 'subtle' : 'secondary'}
            onClick={() => toggleWatch.mutate()}
            loading={toggleWatch.isPending}
          >
            {watching ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            {watching ? 'Unwatch' : 'Watch'}
          </Button>
        </div>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-800">Labels</h3>
          <LabelPicker
            labels={labels.data ?? []}
            selectedIds={current.labels.map((label) => label.id)}
            onChange={(ids) => patch.mutate({ label_ids: ids })}
          />
        </section>

        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-baseline gap-2">
              <h3 className="text-sm font-semibold text-slate-800">Subtasks</h3>
              {current.child_count > 0 && (
                <span className="text-xs text-slate-400">
                  {current.done_child_count}/{current.child_count} done
                </span>
              )}
            </div>
            {onAddChild && current.type !== 'task' && (
              <Button size="sm" variant="secondary" onClick={() => onAddChild(current)}>
                <Plus className="h-3.5 w-3.5" /> Add subtask
              </Button>
            )}
          </div>
          <div className="divide-y divide-slate-100 overflow-hidden rounded-lg border border-slate-200">
            {children.data?.map((child) => (
              <button
                key={child.id}
                type="button"
                onClick={() => onOpenTask?.(child)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-slate-50"
              >
                <Badge className={TYPE_BADGE[child.type]}>{TYPE_LABELS[child.type]}</Badge>
                <span className="min-w-0 flex-1 truncate text-sm text-slate-700">{child.title}</span>
                {child.child_count > 0 && (
                  <span className="text-[10px] text-slate-400">
                    {child.done_child_count}/{child.child_count}
                  </span>
                )}
                <Badge className={STATUS_BADGE[child.status]}>{STATUS_LABELS[child.status]}</Badge>
              </button>
            ))}
            {children.data?.length === 0 && (
              <p className="px-3 py-3 text-xs text-slate-400">
                {current.type === 'task'
                  ? 'Tasks are the deepest level.'
                  : 'No subtasks yet — break this work down.'}
              </p>
            )}
          </div>
        </section>

        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-800">Description</h3>
            {description !== (current.description ?? '') && (
              <Button
                size="sm"
                onClick={() => patch.mutate({ description: description || null })}
                loading={patch.isPending}
              >
                Save
              </Button>
            )}
          </div>
          <MarkdownEditor
            value={description}
            onChange={setDescription}
            maxLength={20_000}
            minRows={6}
            placeholder="Add context, acceptance criteria, links…"
          />
        </section>

        <AttachmentsSection taskId={current.id} />

        <CommentsSection taskId={current.id} />

        <section className="grid gap-2 rounded-lg border border-slate-200 px-3 py-3 text-xs text-slate-500 sm:grid-cols-2">
          <p>
            <span className="font-medium text-slate-600">Created</span>{' '}
            {formatDateTime(current.created_at)}
            {current.creator && ` by ${current.creator.full_name || current.creator.email}`}
          </p>
          <p>
            <span className="font-medium text-slate-600">Updated</span>{' '}
            {current.updated_at ? relativeTime(current.updated_at) : '—'}
          </p>
          <p className="flex items-center gap-1">
            <CalendarDays className="h-3.5 w-3.5" />
            Due {formatDateTime(current.due_date)}
          </p>
        </section>

        {canDelete && (
          <section className={cn('flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-3 py-3')}>
            <div>
              <p className="text-sm font-medium text-red-800">Delete this task</p>
              <p className="text-xs text-red-600">
                Subtasks are kept and become top level. This cannot be undone.
              </p>
            </div>
            <Button variant="danger" size="sm" onClick={() => setConfirmDelete(true)}>
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </Button>
          </section>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete task"
        message={`Delete "${current.title}"? This cannot be undone.`}
        busy={remove.isPending}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => remove.mutate()}
      />
    </Drawer>
  )
}

import { useMutation, useQuery } from '@tanstack/react-query'
import { CalendarDays, Eye, EyeOff, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useAuth } from '../../contexts/auth'
import { useToast } from '../../contexts/toast'
import { ApiError, tasksApi } from '../../lib/api'
import { qk, useInvalidateTasks, useLabels } from '../../lib/hooks'
import {
  PRIORITIES,
  PRIORITY_BADGE,
  PRIORITY_LABELS,
  STATUS_BADGE,
  STATUS_LABELS,
  STATUS_TRANSITIONS,
  type TaskPriority,
  type TaskRead,
  type TaskStatus,
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
  Textarea,
} from '../ui'
import { AttachmentsSection } from './AttachmentsSection'
import { CommentsSection } from './CommentsSection'
import { LabelPicker } from './LabelPicker'

export function TaskDetailDrawer({
  task,
  onClose,
}: {
  task: TaskRead | null
  onClose: () => void
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

  const current = detail.data ?? task

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

  return (
    <Drawer
      open
      wide
      onClose={onClose}
      title={
        <div className="min-w-0 pr-2">
          <div className="flex items-center gap-2">
            <Badge className={STATUS_BADGE[current.status]}>{STATUS_LABELS[current.status]}</Badge>
            <Badge className={PRIORITY_BADGE[current.priority]}>
              {PRIORITY_LABELS[current.priority]}
            </Badge>
          </div>
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
          <Textarea
            value={description}
            maxLength={20_000}
            placeholder="Add context, acceptance criteria, links…"
            onChange={(event) => setDescription(event.target.value)}
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
              <p className="text-xs text-red-600">This cannot be undone.</p>
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

import { useMutation, useQuery } from '@tanstack/react-query'
import { CalendarDays, CornerDownRight, Eye, EyeOff, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useAuth } from '../../contexts/auth'
import { useToast } from '../../contexts/toast'
import { ApiError, tasksApi } from '../../lib/api'
import {
  qk,
  useInvalidateTasks,
  useLabels,
  useReleases,
  useSprints,
  useTaskChildren,
  useWorkflow,
} from '../../lib/hooks'
import { useI18n } from '../../lib/i18n'
import {
  CATEGORY_BADGE,
  PRIORITIES,
  PRIORITY_BADGE,
  PRIORITY_LABELS,
  TASK_TYPES,
  TYPE_BADGE,
  TYPE_LABELS,
  allowedParentTypes,
  statusName,
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
import { ActivityFeed } from './ActivityFeed'
import { AttachmentsSection } from './AttachmentsSection'
import { CommentsSection } from './CommentsSection'
import { LabelPicker } from './LabelPicker'
import {
  AssigneesEditor,
  ChecklistSection,
  CustomFieldsEditor,
  LinksSection,
  WorklogSection,
} from './TaskExtras'

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
  const { t } = useI18n()

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
  const releases = useReleases(current?.project_id)
  const workflow = useWorkflow(current?.project_id)
  const [customRule, setCustomRule] = useState('')

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
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : t('tasks.couldNotUpdate', 'Could not update task')),
  })

  const move = useMutation({
    mutationFn: (status: TaskStatus) => tasksApi.move(current!.id, status),
    onSuccess: () => invalidate(org.slug, current!.id),
    onError: (err) =>
      toast.error(
        err instanceof ApiError
          ? err.message
          : t('tasks.statusChangeNotAllowed', 'That status change is not allowed'),
      ),
  })

  const toggleWatch = useMutation({
    mutationFn: () =>
      watching ? tasksApi.unwatch(current!.id) : tasksApi.watch(current!.id),
    onSuccess: () => invalidate(org.slug, current!.id),
    onError: (err) =>
      toast.error(
        err instanceof ApiError
          ? err.message
          : t('tasks.couldNotUpdateWatcher', 'Could not update watcher'),
      ),
  })

  const remove = useMutation({
    mutationFn: () => tasksApi.remove(current!.id),
    onSuccess: () => {
      invalidate(org.slug)
      toast.success(t('tasks.taskDeleted', 'Task deleted'))
      onClose()
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : t('tasks.couldNotDelete', 'Could not delete task')),
  })

  if (!task || !current) return null

  const watching = current.watcher_ids.includes(user?.id ?? '')
  const canDelete = role !== 'member' || current.created_by_id === user?.id
  const workflowMap = new Map((workflow.data ?? []).map((entry) => [entry.key, entry]))
  const currentWorkflowStatus = workflowMap.get(current.status)
  const statusOptions: string[] = currentWorkflowStatus
    ? [current.status, ...currentWorkflowStatus.transitions.filter((key) => workflowMap.has(key))]
    : [current.status]
  const RECURRENCE_PRESETS = ['FREQ=DAILY', 'FREQ=WEEKLY', 'FREQ=MONTHLY']
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
      toast.error(t('tasks.couldNotOpenParent', 'Could not open the parent task'))
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
            <Badge className={TYPE_BADGE[current.type]}>
              {t(`type.${current.type}`, TYPE_LABELS[current.type])}
            </Badge>
            <Badge className={CATEGORY_BADGE[current.status_category]}>
              {statusName(workflow.data, current.status)}
            </Badge>
            {current.is_blocked && (
              <Badge className="bg-red-100 text-red-700">{t('tasks.blocked', 'blocked')}</Badge>
            )}
            <Badge className={PRIORITY_BADGE[current.priority]}>
              {t(`priority.${current.priority}`, PRIORITY_LABELS[current.priority])}
            </Badge>
            {current.key && (
              <span className="font-mono text-[11px] text-slate-400">{current.key}</span>
            )}
            {current.estimate != null && (
              <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                {t('tasks.points', '{points} pts', { points: current.estimate })}
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
              {t('tasks.parentRef', '{type} · {title}', {
                type: t(`type.${current.parent.type}`, TYPE_LABELS[current.parent.type]),
                title: current.parent.title,
              })}
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
              {t('common.save', 'Save')}
            </Button>
          )}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('common.status', 'Status')}>
            <Select
              value={current.status}
              onChange={(event) => move.mutate(event.target.value as TaskStatus)}
            >
              {statusOptions.map((status) => (
                <option key={status} value={status}>
                  {status === current.status
                    ? t('tasks.currentOption', '{status} (current)', {
                        status: statusName(workflow.data, status),
                      })
                    : statusName(workflow.data, status)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('common.priority', 'Priority')}>
            <Select
              value={current.priority}
              onChange={(event) =>
                patch.mutate({ priority: event.target.value as TaskPriority })
              }
            >
              {PRIORITIES.map((priority) => (
                <option key={priority} value={priority}>
                  {t(`priority.${priority}`, PRIORITY_LABELS[priority])}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label={t('common.type', 'Type')}
            hint={
              current.child_count > 0
                ? t('tasks.hasChildrenHint', 'Has children — keep the level lower than theirs')
                : undefined
            }
          >
            <Select value={current.type} onChange={(event) => changeType(event.target.value as TaskType)}>
              {TASK_TYPES.map((value) => (
                <option key={value} value={value}>
                  {t(`type.${value}`, TYPE_LABELS[value])}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label={t('tasks.parent', 'Parent')}
            hint={
              parentTypes.length === 0
                ? t('tasks.epicsTopLevel', 'Epics are always top level')
                : undefined
            }
          >
            <Select
              value={current.parent_id ?? ''}
              disabled={parentTypes.length === 0}
              onChange={(event) => patch.mutate({ parent_id: event.target.value || null })}
            >
              <option value="">{t('tasks.noParentTopLevel', 'No parent (top level)')}</option>
              {parentCandidates.map((parent) => (
                <option key={parent.id} value={parent.id}>
                  {t('tasks.parentOption', '[{type}] {title}', {
                    type: t(`type.${parent.type}`, TYPE_LABELS[parent.type]),
                    title: parent.title,
                  })}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('common.assignee', 'Assignee')}>
            <Select
              value={current.assignee_id ?? ''}
              onChange={(event) => patch.mutate({ assignee_id: event.target.value || null })}
            >
              <option value="">{t('common.unassigned', 'Unassigned')}</option>
              {members.map((membership) => (
                <option key={membership.user_id} value={membership.user_id}>
                  {membership.user?.full_name || membership.user?.email || membership.user_id}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('common.dueDate', 'Due date')}>
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
          <Field label={t('tasks.sprint', 'Sprint')}>
            <Select
              value={current.sprint_id ?? ''}
              onChange={(event) => patch.mutate({ sprint_id: event.target.value || null })}
            >
              <option value="">{t('tasks.backlogNoSprint', 'Backlog (no sprint)')}</option>
              {(sprints.data ?? [])
                .filter(
                  (sprint) =>
                    sprint.state !== 'completed' || sprint.id === current.sprint_id,
                )
                .map((sprint) => (
                  <option key={sprint.id} value={sprint.id}>
                    {sprint.state === 'active'
                      ? t('tasks.sprintOptionActive', '{name} (active)', { name: sprint.name })
                      : sprint.state === 'completed'
                        ? t('tasks.sprintOptionCompleted', '{name} (completed)', {
                            name: sprint.name,
                          })
                        : sprint.name}
                  </option>
                ))}
            </Select>
          </Field>
          <Field label={t('tasks.release', 'Release')}>
            <Select
              value={current.release_id ?? ''}
              onChange={(event) => patch.mutate({ release_id: event.target.value || null })}
            >
              <option value="">{t('tasks.noRelease', 'No release')}</option>
              {(releases.data ?? []).map((release) => (
                <option key={release.id} value={release.id}>
                  {release.release_date
                    ? t('tasks.releaseOption', '{name} · {date}', {
                        name: release.name,
                        date: release.release_date.slice(0, 10),
                      })
                    : release.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label={t('tasks.estimate', 'Estimate')}
            hint={t('tasks.estimateHintPoints', 'Points or hours per project setting')}
          >
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
          <Field label={t('tasks.remaining', 'Remaining')}>
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
          <Field
            label={t('tasks.recurrence', 'Recurrence')}
            hint={t('tasks.recurrenceHint', 'Completing this task creates the next occurrence')}
          >
            <Select
              value={
                current.recurrence_rule == null
                  ? ''
                  : RECURRENCE_PRESETS.includes(current.recurrence_rule)
                    ? current.recurrence_rule
                    : 'custom'
              }
              onChange={(event) => {
                if (event.target.value === 'custom') {
                  setCustomRule(current.recurrence_rule ?? '')
                } else {
                  patch.mutate({ recurrence_rule: event.target.value || null })
                }
              }}
            >
              <option value="">{t('tasks.doesNotRepeat', 'Does not repeat')}</option>
              <option value="FREQ=DAILY">{t('tasks.daily', 'Daily')}</option>
              <option value="FREQ=WEEKLY">{t('tasks.weekly', 'Weekly')}</option>
              <option value="FREQ=MONTHLY">{t('tasks.monthly', 'Monthly')}</option>
              <option value="custom">{t('tasks.customRrule', 'Custom RRULE…')}</option>
            </Select>
            {customRule !== '' && (
              <Input
                className="mt-1 font-mono text-xs"
                value={customRule}
                placeholder={t('tasks.rrulePlaceholder', 'FREQ=WEEKLY;BYDAY=MO,WE,FR')}
                onChange={(event) => setCustomRule(event.target.value)}
                onBlur={() => patch.mutate({ recurrence_rule: customRule || null })}
              />
            )}
          </Field>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-slate-50 px-3 py-2.5">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-slate-500">{t('tasks.watchers', 'Watchers')}</span>
            <div className="flex -space-x-1.5">
              {watchers.slice(0, 5).map((membership) => (
                <Avatar
                  key={membership.user_id}
                  name={membership.user?.full_name || membership.user?.email || '?'}
                  email={membership.user?.email}
                  size="sm"
                />
              ))}
              {watchers.length === 0 && (
                <span className="text-xs text-slate-400">{t('tasks.watchersNone', 'none')}</span>
              )}
            </div>
          </div>
          <Button
            size="sm"
            variant={watching ? 'subtle' : 'secondary'}
            onClick={() => toggleWatch.mutate()}
            loading={toggleWatch.isPending}
          >
            {watching ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            {watching
              ? t('tasks.unwatch', 'Unwatch')
              : t('tasks.watch', 'Watch')}
          </Button>
        </div>

        <section className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-800">{t('common.labels', 'Labels')}</h3>
          <LabelPicker
            labels={labels.data ?? []}
            selectedIds={current.labels.map((label) => label.id)}
            onChange={(ids) => patch.mutate({ label_ids: ids })}
          />
        </section>

        <CustomFieldsEditor task={current} />

        <ChecklistSection taskId={current.id} />

        <AssigneesEditor taskId={current.id} />

        <LinksSection task={current} />

        <WorklogSection task={current} />

        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-baseline gap-2">
              <h3 className="text-sm font-semibold text-slate-800">{t('tasks.subtasks', 'Subtasks')}</h3>
              {current.child_count > 0 && (
                <span className="text-xs text-slate-400">
                  {t('tasks.doneCount', '{done}/{total} done', {
                    done: current.done_child_count,
                    total: current.child_count,
                  })}
                </span>
              )}
            </div>
            {onAddChild && current.type !== 'task' && (
              <Button size="sm" variant="secondary" onClick={() => onAddChild(current)}>
                <Plus className="h-3.5 w-3.5" /> {t('tasks.addSubtask', 'Add subtask')}
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
                <Badge className={TYPE_BADGE[child.type]}>
                  {t(`type.${child.type}`, TYPE_LABELS[child.type])}
                </Badge>
                <span className="min-w-0 flex-1 truncate text-sm text-slate-700">{child.title}</span>
                {child.child_count > 0 && (
                  <span className="text-[10px] text-slate-400">
                    {child.done_child_count}/{child.child_count}
                  </span>
                )}
                <Badge className={CATEGORY_BADGE[child.status_category]}>
                  {statusName(workflow.data, child.status)}
                </Badge>
              </button>
            ))}
            {children.data?.length === 0 && (
              <p className="px-3 py-3 text-xs text-slate-400">
                {current.type === 'task'
                  ? t('tasks.deepestLevel', 'Tasks are the deepest level.')
                  : t('tasks.noSubtasks', 'No subtasks yet — break this work down.')}
              </p>
            )}
          </div>
        </section>

        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-800">
              {t('common.description', 'Description')}
            </h3>
            {description !== (current.description ?? '') && (
              <Button
                size="sm"
                onClick={() => patch.mutate({ description: description || null })}
                loading={patch.isPending}
              >
                {t('common.save', 'Save')}
              </Button>
            )}
          </div>
          <MarkdownEditor
            value={description}
            onChange={setDescription}
            maxLength={20_000}
            minRows={6}
            placeholder={t('tasks.descriptionPlaceholder', 'Add context, acceptance criteria, links…')}
          />
        </section>

        <AttachmentsSection
          taskId={current.id}
          onInsertMarkdown={(markdown) =>
            setDescription((value) => `${value ? `${value}\n\n` : ''}${markdown}`)
          }
        />

        <CommentsSection taskId={current.id} />

        <section className="space-y-1">
          <h3 className="text-sm font-semibold text-slate-800">{t('tasks.activity', 'Activity')}</h3>
          <ActivityFeed scope={{ type: 'task', id: current.id }} />
        </section>

        <section className="grid gap-2 rounded-lg border border-slate-200 px-3 py-3 text-xs text-slate-500 sm:grid-cols-2">
          <p>
            {current.creator
              ? t('tasks.createdBy', 'Created {date} by {name}', {
                  date: formatDateTime(current.created_at),
                  name: current.creator.full_name || current.creator.email,
                })
              : t('tasks.createdAt', 'Created {date}', {
                  date: formatDateTime(current.created_at),
                })}
          </p>
          <p>
            {t('tasks.updatedAt', 'Updated {date}', {
              date: current.updated_at ? relativeTime(current.updated_at) : '—',
            })}
          </p>
          <p className="flex items-center gap-1">
            <CalendarDays className="h-3.5 w-3.5" />
            {t('tasks.dueAt', 'Due {date}', { date: formatDateTime(current.due_date) })}
          </p>
        </section>

        {canDelete && (
          <section className={cn('flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-3 py-3')}>
            <div>
              <p className="text-sm font-medium text-red-800">
                {t('tasks.deleteThisTask', 'Delete this task')}
              </p>
              <p className="text-xs text-red-600">
                {t(
                  'tasks.deleteKeepsSubtasks',
                  'Subtasks are kept and become top level. This cannot be undone.',
                )}
              </p>
            </div>
            <Button variant="danger" size="sm" onClick={() => setConfirmDelete(true)}>
              <Trash2 className="h-3.5 w-3.5" /> {t('common.delete', 'Delete')}
            </Button>
          </section>
        )}
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title={t('tasks.deleteTaskTitle', 'Delete task')}
        message={t('tasks.deleteConfirm', 'Delete "{title}"? This cannot be undone.', {
          title: current.title,
        })}
        busy={remove.isPending}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => remove.mutate()}
      />
    </Drawer>
  )
}

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link2, Pencil, Plus, Search, Target, Trash2, X } from 'lucide-react'
import { useMemo, useState } from 'react'

import { useOrg } from '../components/OrgLayout'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Modal,
  PageSpinner,
  Select,
  Textarea,
} from '../components/ui'
import { useToast } from '../contexts/toast'
import { ApiError, goalsApi } from '../lib/api'
import { qk, useGoals, useTasks } from '../lib/hooks'
import { useI18n } from '../lib/i18n'
import {
  GOAL_STATUS_BADGE,
  GOAL_STATUS_LABELS,
  STATUS_BADGE,
  TYPE_LABELS,
  type GoalRead,
  type GoalStatus,
  type TaskType,
} from '../lib/types'
import { cn, formatDate, fromDateTimeLocal, toDateTimeLocal } from '../lib/utils'

interface GoalForm {
  name: string
  description: string
  status: GoalStatus
  dueDate: string
  ownerId: string
}

const EMPTY_FORM: GoalForm = {
  name: '',
  description: '',
  status: 'active',
  dueDate: '',
  ownerId: '',
}

export function GoalsPage() {
  const { org, members } = useOrg()
  const { t } = useI18n()
  const toast = useToast()
  const queryClient = useQueryClient()
  const goals = useGoals(org.slug)

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<GoalRead | null>(null)
  const [form, setForm] = useState<GoalForm>(EMPTY_FORM)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<GoalRead | null>(null)
  const [linkSearch, setLinkSearch] = useState('')

  const linkQuery = useTasks(org.slug, {
    search: linkSearch.trim(),
    type: ['epic', 'task'],
    limit: 10,
  })

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: qk.goals(org.slug) })

  const save = useMutation({
    mutationFn: () => {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        status: form.status,
        due_date: form.dueDate ? fromDateTimeLocal(form.dueDate) : null,
        owner_id: form.ownerId || null,
      }
      return editing
        ? goalsApi.update(org.slug, editing.id, payload)
        : goalsApi.create(org.slug, payload)
    },
    onSuccess: () => {
      invalidate()
      setFormOpen(false)
      setEditing(null)
      setError(null)
      toast.success(editing ? t('goals.updated', 'Goal updated') : t('goals.created', 'Goal created'))
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : t('goals.saveError', 'Could not save goal')),
  })

  const remove = useMutation({
    mutationFn: (goal: GoalRead) => goalsApi.remove(org.slug, goal.id),
    onSuccess: () => {
      invalidate()
      setDeleting(null)
      if (editing && deleting && editing.id === deleting.id) setEditing(null)
      toast.success(t('goals.deleted', 'Goal deleted'))
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError ? err.message : t('goals.deleteError', 'Could not delete goal'),
      ),
  })

  const link = useMutation({
    mutationFn: ({ goalId, taskId }: { goalId: string; taskId: string }) =>
      goalsApi.linkTasks(org.slug, goalId, [taskId]),
    onSuccess: (goal) => {
      invalidate()
      setEditing(goal)
      setLinkSearch('')
      toast.success(t('goals.taskLinked', 'Task linked'))
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError ? err.message : t('goals.linkError', 'Could not link task'),
      ),
  })

  const unlink = useMutation({
    mutationFn: ({ goalId, taskId }: { goalId: string; taskId: string }) =>
      goalsApi.unlinkTask(org.slug, goalId, taskId),
    onSuccess: (goal) => {
      invalidate()
      setEditing(goal)
    },
    onError: (err) =>
      toast.error(
        err instanceof ApiError ? err.message : t('goals.unlinkError', 'Could not unlink task'),
      ),
  })

  const liveEditing = useMemo(
    () => (editing ? (goals.data?.find((goal) => goal.id === editing.id) ?? editing) : null),
    [editing, goals.data],
  )

  function openCreate() {
    setEditing(null)
    setForm(EMPTY_FORM)
    setError(null)
    setLinkSearch('')
    setFormOpen(true)
  }

  function openEdit(goal: GoalRead) {
    setEditing(goal)
    setForm({
      name: goal.name,
      description: goal.description ?? '',
      status: (goal.status as GoalStatus) ?? 'active',
      dueDate: toDateTimeLocal(goal.due_date),
      ownerId: goal.owner_id ?? '',
    })
    setError(null)
    setLinkSearch('')
    setFormOpen(true)
  }

  function goalMeta(goal: GoalRead): string {
    return [
      goal.owner
        ? t('goals.ownerLabel', 'Owner {name}', { name: goal.owner.full_name })
        : null,
      goal.due_date
        ? t('goals.dueLabel', 'Due {date}', { date: formatDate(goal.due_date) })
        : null,
      goal.tasks.length === 1
        ? t('goals.linkedTaskOne', '{count} linked task', { count: goal.tasks.length })
        : t('goals.linkedTaskMany', '{count} linked tasks', { count: goal.tasks.length }),
    ]
      .filter(Boolean)
      .join(' · ')
  }

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">{t('goals.title', 'Goals')}</h1>
          <p className="text-sm text-slate-500">
            {t('goals.subtitle', 'Objectives linked to work items, with rolled-up progress.')}
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="h-4 w-4" /> {t('goals.new', 'New goal')}
        </Button>
      </div>

      {goals.isLoading && <PageSpinner label={t('goals.loading', 'Loading goals…')} />}
      {goals.isError && (
        <ErrorState
          message={t('goals.loadError', 'Could not load goals.')}
          onRetry={() => void goals.refetch()}
        />
      )}
      {goals.data?.length === 0 && (
        <EmptyState
          icon={<Target className="h-8 w-8" />}
          title={t('goals.emptyTitle', 'No goals yet')}
          description={t(
            'goals.emptyDescription',
            'Create an objective and link epics or tasks to track progress.',
          )}
          action={<Button onClick={openCreate}>{t('goals.create', 'Create a goal')}</Button>}
        />
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {goals.data?.map((goal) => (
          <Card key={goal.id}>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  {goal.name}
                  <Badge
                    className={
                      GOAL_STATUS_BADGE[(goal.status as GoalStatus) ?? 'active'] ??
                      'bg-slate-100 text-slate-600'
                    }
                  >
                    {t(
                      `goalStatus.${(goal.status as GoalStatus) ?? 'active'}`,
                      GOAL_STATUS_LABELS[(goal.status as GoalStatus) ?? 'active'] ?? goal.status,
                    )}
                  </Badge>
                </span>
              }
              description={goalMeta(goal)}
              action={
                <div className="flex items-center gap-1">
                  <Button size="sm" variant="ghost" onClick={() => openEdit(goal)}>
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <button
                    className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                    title={t('goals.deleteTitle', 'Delete goal')}
                    onClick={() => setDeleting(goal)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              }
            />
            <div className="space-y-3 p-5">
              {goal.description && (
                <p className="text-sm text-slate-600">{goal.description}</p>
              )}
              <div>
                <div className="flex items-center justify-between text-xs text-slate-500">
                  <span>{t('goals.progress', 'Progress')}</span>
                  <span>{goal.progress_pct}%</span>
                </div>
                <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className={cn(
                      'h-full rounded-full transition-all',
                      goal.progress_pct >= 100 ? 'bg-emerald-500' : 'bg-brand-500',
                    )}
                    style={{ width: `${Math.min(goal.progress_pct, 100)}%` }}
                  />
                </div>
              </div>
              {goal.tasks.length > 0 && (
                <ul className="space-y-1.5">
                  {goal.tasks.map((task) => (
                    <li
                      key={task.id}
                      className="flex items-center gap-2 rounded-lg border border-slate-100 px-2.5 py-1.5"
                    >
                      <span className="min-w-0 flex-1 truncate text-sm text-slate-700">
                        {task.key ? `${task.key} · ` : ''}
                        {task.title}
                      </span>
                      <Badge
                        className={
                          STATUS_BADGE[task.status_category as keyof typeof STATUS_BADGE] ??
                          'bg-slate-100 text-slate-600'
                        }
                      >
                        {t(`status.${task.status}`, task.status)}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </Card>
        ))}
      </div>

      <Modal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title={editing ? t('goals.edit', 'Edit goal') : t('goals.new', 'New goal')}
        size="lg"
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
              {t('goals.save', 'Save goal')}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {error && <ErrorState message={error} />}
          <Field label={t('common.name', 'Name')}>
            <Input
              autoFocus
              value={form.name}
              maxLength={128}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
          </Field>
          <Field label={t('common.description', 'Description')}>
            <Textarea
              value={form.description}
              maxLength={20_000}
              onChange={(event) => setForm({ ...form, description: event.target.value })}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={t('common.status', 'Status')}>
              <Select
                value={form.status}
                onChange={(event) =>
                  setForm({ ...form, status: event.target.value as GoalStatus })
                }
              >
                {(['active', 'achieved', 'cancelled'] as GoalStatus[]).map((status) => (
                  <option key={status} value={status}>
                    {t(`goalStatus.${status}`, GOAL_STATUS_LABELS[status])}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t('common.dueDate', 'Due date')}>
              <Input
                type="datetime-local"
                value={form.dueDate}
                onChange={(event) => setForm({ ...form, dueDate: event.target.value })}
              />
            </Field>
            <Field label={t('goals.owner', 'Owner')}>
              <Select
                value={form.ownerId}
                onChange={(event) => setForm({ ...form, ownerId: event.target.value })}
              >
                <option value="">{t('common.unassigned', 'Unassigned')}</option>
                {members.map((membership) => (
                  <option key={membership.user_id} value={membership.user_id}>
                    {membership.user?.full_name || membership.user?.email}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          {liveEditing && (
            <div className="space-y-2 rounded-lg border border-slate-200 p-3">
              <p className="flex items-center gap-1.5 text-sm font-medium text-slate-700">
                <Link2 className="h-3.5 w-3.5" /> {t('goals.linkedItems', 'Linked work items')}
              </p>
              {liveEditing.tasks.length === 0 && (
                <p className="text-xs text-slate-400">{t('goals.nothingLinked', 'Nothing linked yet.')}</p>
              )}
              <ul className="space-y-1">
                {liveEditing.tasks.map((task) => (
                  <li key={task.id} className="flex items-center gap-2 text-sm">
                    <span className="min-w-0 flex-1 truncate text-slate-700">
                      {task.key ? `${task.key} · ` : ''}
                      {task.title}
                    </span>
                    <Badge>
                      {t(`type.${task.type}`, TYPE_LABELS[task.type as TaskType] ?? task.type)}
                    </Badge>
                    <button
                      className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                      title={t('goals.unlink', 'Unlink')}
                      onClick={() => unlink.mutate({ goalId: liveEditing.id, taskId: task.id })}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
              <div className="flex items-center gap-2">
                <div className="relative flex-1">
                  <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
                  <Input
                    className="pl-8"
                    value={linkSearch}
                    placeholder={t('goals.searchPlaceholder', 'Search epics and tasks…')}
                    onChange={(event) => setLinkSearch(event.target.value)}
                  />
                </div>
              </div>
              {linkSearch.trim().length >= 2 && (
                <ul className="max-h-40 space-y-1 overflow-y-auto">
                  {(linkQuery.data?.items ?? [])
                    .filter(
                      (task) => !liveEditing.tasks.some((linked) => linked.id === task.id),
                    )
                    .map((task) => (
                      <li
                        key={task.id}
                        className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-slate-50"
                      >
                        <span className="min-w-0 flex-1 truncate text-slate-700">
                          {task.key ? `${task.key} · ` : ''}
                          {task.title}
                        </span>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() =>
                            link.mutate({ goalId: liveEditing.id, taskId: task.id })
                          }
                        >
                          {t('goals.link', 'Link')}
                        </Button>
                      </li>
                    ))}
                  {linkQuery.isFetching && (
                    <li className="px-2 py-1 text-xs text-slate-400">
                      {t('goals.searching', 'Searching…')}
                    </li>
                  )}
                </ul>
              )}
            </div>
          )}
        </div>
      </Modal>

      <ConfirmDialog
        open={Boolean(deleting)}
        title={t('goals.deleteTitle', 'Delete goal')}
        message={t('goals.deleteMessage', 'Delete "{name}"? Linked tasks are not affected.', {
          name: deleting?.name ?? '',
        })}
        busy={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </div>
  )
}

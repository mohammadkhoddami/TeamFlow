import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, Play, Plus, Trash2, CheckCircle2 } from 'lucide-react'
import { useState } from 'react'

import { useToast } from '../../contexts/toast'
import { ApiError, sprintsApi } from '../../lib/api'
import { qk, useSprints } from '../../lib/hooks'
import { useI18n } from '../../lib/i18n'
import type { SprintRead } from '../../lib/types'
import { formatDate } from '../../lib/utils'
import { Badge, Button, Field, Input, Modal, Select } from '../ui'

const STATE_BADGE: Record<SprintRead['state'], string> = {
  planned: 'bg-slate-100 text-slate-600',
  active: 'bg-emerald-100 text-emerald-700',
  completed: 'bg-slate-100 text-slate-400',
}

const STATE_LABELS: Record<SprintRead['state'], string> = {
  planned: 'Planned',
  active: 'Active',
  completed: 'Completed',
}

export function SprintManager({
  projectId,
  open,
  onClose,
}: {
  projectId: string
  open: boolean
  onClose: () => void
}) {
  const { t } = useI18n()
  const sprints = useSprints(projectId)
  const queryClient = useQueryClient()
  const toast = useToast()

  const [name, setName] = useState('')
  const [goal, setGoal] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [carryOver, setCarryOver] = useState<Record<string, string>>({})

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.sprints(projectId) })
    void queryClient.invalidateQueries({ queryKey: ['orgs'] })
  }

  const create = useMutation({
    mutationFn: () =>
      sprintsApi.create(projectId, {
        name: name.trim(),
        goal: goal.trim() || null,
        start_date: startDate ? new Date(startDate).toISOString() : null,
        end_date: endDate ? new Date(endDate).toISOString() : null,
      }),
    onSuccess: () => {
      invalidate()
      setName('')
      setGoal('')
      setStartDate('')
      setEndDate('')
      toast.success(t('sprints.created', 'Sprint created'))
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('sprints.createError', 'Could not create sprint')),
  })

  const start = useMutation({
    mutationFn: (sprintId: string) => sprintsApi.start(sprintId),
    onSuccess: () => {
      invalidate()
      toast.success(t('sprints.started', 'Sprint started'))
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('sprints.startError', 'Could not start sprint')),
  })

  const complete = useMutation({
    mutationFn: (sprintId: string) =>
      sprintsApi.complete(sprintId, carryOver[sprintId] || null),
    onSuccess: (sprint) => {
      invalidate()
      toast.success(
        sprint.carried_over_count
          ? t(
              'sprints.completedCarriedOver',
              'Sprint completed — {count} task(s) carried over',
              { count: sprint.carried_over_count },
            )
          : t('sprints.completed', 'Sprint completed'),
      )
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : t('sprints.completeError', 'Could not complete sprint')),
  })

  const remove = useMutation({
    mutationFn: (sprintId: string) => sprintsApi.remove(sprintId),
    onSuccess: () => {
      invalidate()
      toast.success(t('sprints.deleted', 'Sprint deleted — its tasks are back in the backlog'))
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('sprints.deleteError', 'Could not delete sprint')),
  })

  const list = sprints.data ?? []

  return (
    <Modal open={open} onClose={onClose} title={t('sprints.title', 'Sprints')} size="lg">
      <div className="space-y-5">
        <section className="space-y-2">
          {list.map((sprint) => (
            <div
              key={sprint.id}
              className="rounded-lg border border-slate-200 px-3 py-2.5"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Badge className={STATE_BADGE[sprint.state]}>
                      {t(`sprintState.${sprint.state}`, STATE_LABELS[sprint.state])}
                    </Badge>
                    <p className="truncate text-sm font-medium text-slate-800">{sprint.name}</p>
                  </div>
                  <p className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-400">
                    <span>
                      {t('sprints.doneProgress', '{done}/{total} done', {
                        done: sprint.done_task_count,
                        total: sprint.task_count,
                      })}
                    </span>
                    {sprint.total_estimate ? (
                      <span>
                        {t('sprints.pointsProgress', '{done}/{total} pts', {
                          done: sprint.done_estimate ?? 0,
                          total: sprint.total_estimate,
                        })}
                      </span>
                    ) : null}
                    {(sprint.start_date || sprint.end_date) && (
                      <span className="inline-flex items-center gap-1">
                        <CalendarDays className="h-3 w-3" />
                        {sprint.start_date ? formatDate(sprint.start_date) : '?'} –{' '}
                        {sprint.end_date ? formatDate(sprint.end_date) : '?'}
                      </span>
                    )}
                  </p>
                  {sprint.goal && (
                    <p className="mt-1 line-clamp-2 text-xs text-slate-500">{sprint.goal}</p>
                  )}
                </div>
                <div className="flex items-center gap-1.5">
                  {sprint.state === 'planned' && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => start.mutate(sprint.id)}
                      loading={start.isPending}
                    >
                      <Play className="h-3.5 w-3.5" /> {t('sprints.start', 'Start')}
                    </Button>
                  )}
                  {sprint.state === 'active' && (
                    <>
                      <Select
                        className="w-auto"
                        value={carryOver[sprint.id] ?? ''}
                        onChange={(event) =>
                          setCarryOver((current) => ({
                            ...current,
                            [sprint.id]: event.target.value,
                          }))
                        }
                      >
                        <option value="">{t('sprints.unfinishedBacklog', 'Unfinished → backlog')}</option>
                        {list
                          .filter((entry) => entry.state === 'planned')
                          .map((entry) => (
                            <option key={entry.id} value={entry.id}>
                              {t('sprints.unfinishedTo', 'Unfinished → {name}', {
                                name: entry.name,
                              })}
                            </option>
                          ))}
                      </Select>
                      <Button
                        size="sm"
                        onClick={() => complete.mutate(sprint.id)}
                        loading={complete.isPending}
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" /> {t('sprints.complete', 'Complete')}
                      </Button>
                    </>
                  )}
                  {sprint.state !== 'active' && (
                    <button
                      type="button"
                      title={t('sprints.deleteSprint', 'Delete sprint (tasks return to the backlog)')}
                      onClick={() => remove.mutate(sprint.id)}
                      className="rounded p-1.5 text-slate-300 hover:bg-red-50 hover:text-red-600"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
          {list.length === 0 && (
            <p className="rounded-lg border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400">
              {t(
                'sprints.empty',
                'No sprints yet. Create one below, then drag tasks into it from the board or assign them from the backlog.',
              )}
            </p>
          )}
        </section>

        <section className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <p className="text-sm font-semibold text-slate-800">
            {t('sprints.newSprint', 'New sprint')}
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('common.name', 'Name')}>
              <Input
                value={name}
                maxLength={255}
                placeholder={t('sprints.namePlaceholder', 'Sprint 5')}
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Field label={t('sprints.goal', 'Goal')}>
              <Input
                value={goal}
                maxLength={10_000}
                placeholder={t('sprints.goalPlaceholder', 'Ship the checkout flow')}
                onChange={(event) => setGoal(event.target.value)}
              />
            </Field>
            <Field label={t('sprints.startDate', 'Start')}>
              <Input
                type="date"
                value={startDate}
                onChange={(event) => setStartDate(event.target.value)}
              />
            </Field>
            <Field label={t('sprints.endDate', 'End')}>
              <Input
                type="date"
                value={endDate}
                onChange={(event) => setEndDate(event.target.value)}
              />
            </Field>
          </div>
          <Button
            onClick={() => create.mutate()}
            loading={create.isPending}
            disabled={!name.trim()}
          >
            <Plus className="h-4 w-4" /> {t('sprints.create', 'Create sprint')}
          </Button>
        </section>
      </div>
    </Modal>
  )
}

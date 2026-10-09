import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'

import { useToast } from '../../contexts/toast'
import { ApiError, tasksApi } from '../../lib/api'
import { useInvalidateTasks } from '../../lib/hooks'
import { useCalendar } from '../../lib/hooks'
import type { CalendarTaskRead, TaskCategory } from '../../lib/types'
import { useI18n } from '../../lib/i18n'
import { cn } from '../../lib/utils'
import { useOrg } from '../OrgLayout'
import { Button, Spinner } from '../ui'

const DAY_LABELS: { key: string; label: string }[] = [
  { key: 'sun', label: 'Sun' },
  { key: 'mon', label: 'Mon' },
  { key: 'tue', label: 'Tue' },
  { key: 'wed', label: 'Wed' },
  { key: 'thu', label: 'Thu' },
  { key: 'fri', label: 'Fri' },
  { key: 'sat', label: 'Sat' },
]
const MONTH_LABELS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

const CATEGORY_CHIP: Record<TaskCategory, string> = {
  todo: 'border-slate-200 bg-white text-slate-700',
  in_progress: 'border-sky-200 bg-sky-50 text-sky-800',
  in_review: 'border-amber-200 bg-amber-50 text-amber-800',
  done: 'border-emerald-200 bg-emerald-50 text-emerald-800 line-through',
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date)
  next.setDate(next.getDate() + days)
  return next
}

function dateKey(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

export function CalendarView({ projectId }: { projectId: string }) {
  const { t } = useI18n()
  const { org } = useOrg()
  const toast = useToast()
  const queryClient = useQueryClient()
  const invalidateTasks = useInvalidateTasks()
  const [anchor, setAnchor] = useState<Date>(() => startOfDay(new Date()))
  const [view, setView] = useState<'month' | 'week'>('month')
  const [dragOver, setDragOver] = useState<string | null>(null)

  const { rangeStart, rangeEnd, days } = useMemo(() => {
    if (view === 'week') {
      const start = addDays(anchor, -anchor.getDay())
      return {
        rangeStart: start,
        rangeEnd: addDays(start, 7),
        days: Array.from({ length: 7 }, (_, index) => addDays(start, index)),
      }
    }
    const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
    const start = addDays(first, -first.getDay())
    return {
      rangeStart: start,
      rangeEnd: addDays(start, 42),
      days: Array.from({ length: 42 }, (_, index) => addDays(start, index)),
    }
  }, [anchor, view])

  const calendar = useCalendar(org.slug, {
    start: rangeStart.toISOString(),
    end: rangeEnd.toISOString(),
    project_id: projectId,
  })

  const reschedule = useMutation({
    mutationFn: ({ taskId, date }: { taskId: string; date: Date }) =>
      tasksApi.update(taskId, { due_date: date.toISOString() }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['orgs', org.slug, 'calendar'] })
      invalidateTasks(org.slug)
      toast.success(t('calendar.rescheduled', 'Task rescheduled'))
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : t('calendar.rescheduleError', 'Could not reschedule task')),
  })

  const byDay = useMemo(() => {
    const map = new Map<string, CalendarTaskRead[]>()
    for (const task of calendar.data?.tasks ?? []) {
      const key = dateKey(new Date(task.due_date))
      const list = map.get(key) ?? []
      list.push(task)
      map.set(key, list)
    }
    return map
  }, [calendar.data])

  const today = dateKey(new Date())

  function navigate(direction: -1 | 1) {
    setAnchor((current) =>
      view === 'week'
        ? addDays(current, direction * 7)
        : new Date(current.getFullYear(), current.getMonth() + direction, 1),
    )
  }

  function handleDrop(event: React.DragEvent, day: Date) {
    event.preventDefault()
    setDragOver(null)
    const taskId = event.dataTransfer.getData('text/task-id')
    if (!taskId) return
    const existing = (calendar.data?.tasks ?? []).find((task) => task.id === taskId)
    const original = existing ? new Date(existing.due_date) : new Date()
    const next = new Date(
      day.getFullYear(),
      day.getMonth(),
      day.getDate(),
      original.getHours(),
      original.getMinutes(),
    )
    reschedule.mutate({ taskId, date: next })
  }

  const monthName = (date: Date) =>
    t(`calendar.month.${date.getMonth()}`, MONTH_LABELS[date.getMonth()])

  const periodLabel =
    view === 'week'
      ? t('calendar.weekRange', '{startDay} {startMonth} – {endDay} {endMonth} {year}', {
          startDay: rangeStart.getDate(),
          startMonth: monthName(rangeStart),
          endDay: addDays(rangeStart, 6).getDate(),
          endMonth: monthName(addDays(rangeStart, 6)),
          year: rangeStart.getFullYear(),
        })
      : t('calendar.monthLabel', '{month} {year}', {
          month: monthName(anchor),
          year: anchor.getFullYear(),
        })

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" onClick={() => navigate(-1)}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <p className="min-w-44 text-center text-sm font-semibold text-slate-800">
            {periodLabel}
          </p>
          <Button size="sm" variant="secondary" onClick={() => navigate(1)}>
            <ChevronRight className="h-4 w-4" />
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setAnchor(startOfDay(new Date()))}>
            {t('common.today', 'Today')}
          </Button>
        </div>
        <div className="flex items-center rounded-lg border border-slate-200 bg-white p-0.5 text-xs font-medium">
          {(['month', 'week'] as const).map((value) => (
            <button
              key={value}
              onClick={() => setView(value)}
              className={cn(
                'rounded-md px-2.5 py-1 capitalize transition-colors',
                view === value
                  ? 'bg-brand-50 text-brand-700'
                  : 'text-slate-500 hover:bg-slate-100',
              )}
            >
              {value === 'month' ? t('common.month', 'Month') : t('common.week', 'Week')}
            </button>
          ))}
        </div>
      </div>

      {calendar.isLoading && (
        <div className="flex justify-center py-8">
          <Spinner className="h-5 w-5 text-slate-400" />
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="grid grid-cols-7 border-b border-slate-200 bg-slate-50">
          {DAY_LABELS.map((entry) => (
            <div
              key={entry.key}
              className="px-2 py-1.5 text-center text-[11px] font-semibold uppercase tracking-wide text-slate-500"
            >
              {t(`calendar.day.${entry.key}`, entry.label)}
            </div>
          ))}
        </div>
        <div className="grid grid-cols-7">
          {days.map((day) => {
            const key = dateKey(day)
            const tasks = byDay.get(key) ?? []
            const inMonth = view === 'week' || day.getMonth() === anchor.getMonth()
            return (
              <div
                key={key}
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragOver(key)
                }}
                onDragLeave={() => setDragOver((current) => (current === key ? null : current))}
                onDrop={(event) => handleDrop(event, day)}
                className={cn(
                  'min-h-24 border-b border-r border-slate-100 p-1 align-top',
                  !inMonth && 'bg-slate-50/60',
                  dragOver === key && 'bg-brand-50/70 ring-1 ring-inset ring-brand-300',
                )}
              >
                <p
                  className={cn(
                    'mb-1 text-right text-[11px] font-medium',
                    key === today
                      ? 'inline-block rounded-full bg-brand-600 px-1.5 text-white'
                      : inMonth
                        ? 'text-slate-500'
                        : 'text-slate-300',
                  )}
                >
                  {day.getDate()}
                </p>
                <div className="space-y-1">
                  {tasks.slice(0, 4).map((task) => (
                    <div
                      key={task.id}
                      draggable
                      onDragStart={(event) => {
                        event.dataTransfer.setData('text/task-id', task.id)
                        event.dataTransfer.effectAllowed = 'move'
                      }}
                      title={`${task.key ?? ''} ${task.title}`}
                      className={cn(
                        'cursor-grab truncate rounded border px-1.5 py-0.5 text-[11px] font-medium shadow-sm',
                        CATEGORY_CHIP[task.status_category],
                      )}
                    >
                      {task.key ? `${task.key} · ` : ''}
                      {task.title}
                    </div>
                  ))}
                  {tasks.length > 4 && (
                    <p className="px-1 text-[10px] text-slate-400">
                      {t('calendar.more', '+{count} more', { count: tasks.length - 4 })}
                    </p>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
      <p className="text-xs text-slate-400">
        {t(
          'calendar.hint',
          'Drag a task to another day to reschedule it. Tasks without due dates are not shown.',
        )}
      </p>
    </div>
  )
}

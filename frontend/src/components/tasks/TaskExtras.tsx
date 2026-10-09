import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link2, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useToast } from '../../contexts/toast'
import { ApiError, checklistApi, linksApi, tasksApi, worklogsApi } from '../../lib/api'
import {
  qk,
  useCustomFields,
  useTaskAssignees,
  useTaskChecklist,
  useTaskLinks,
  useTaskWorklogs,
} from '../../lib/hooks'
import type { TaskRead } from '../../lib/types'
import { formatDateTime } from '../../lib/utils'
import { useI18n } from '../../lib/i18n'
import { useOrg } from '../OrgLayout'
import { Badge, Button, Checkbox, Field, Input, Select } from '../ui'

// ---------------------------------------------------------------- checklist

export function ChecklistSection({ taskId }: { taskId: string }) {
  const { t } = useI18n()
  const checklist = useTaskChecklist(taskId)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [text, setText] = useState('')

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.taskChecklist(taskId) })
    void queryClient.invalidateQueries({ queryKey: qk.task(taskId) })
  }

  const add = useMutation({
    mutationFn: () => checklistApi.add(taskId, text.trim()),
    onSuccess: () => {
      invalidate()
      setText('')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('taskExtras.addItemError', 'Could not add item')),
  })
  const toggle = useMutation({
    mutationFn: ({ itemId, done }: { itemId: string; done: boolean }) =>
      checklistApi.update(taskId, itemId, { is_done: done }),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (itemId: string) => checklistApi.remove(taskId, itemId),
    onSuccess: invalidate,
  })

  const items = checklist.data ?? []
  const done = items.filter((item) => item.is_done).length

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800">
          {t('taskExtras.checklist', 'Checklist')}
        </h3>
        {items.length > 0 && (
          <span className="text-xs text-slate-400">
            {t('taskExtras.checklistProgress', '{done}/{total} done', {
              done,
              total: items.length,
            })}
          </span>
        )}
      </div>
      <div className="space-y-1">
        {items.map((item) => (
          <div key={item.id} className="flex items-center gap-2 rounded-lg border border-slate-200 px-2 py-1.5">
            <input
              type="checkbox"
              checked={item.is_done}
              onChange={(event) => toggle.mutate({ itemId: item.id, done: event.target.checked })}
              className="h-3.5 w-3.5 rounded border-slate-300"
            />
            <span
              className={
                item.is_done
                  ? 'min-w-0 flex-1 truncate text-sm text-slate-400 line-through'
                  : 'min-w-0 flex-1 truncate text-sm text-slate-700'
              }
            >
              {item.text}
            </span>
            <button
              type="button"
              onClick={() => remove.mutate(item.id)}
              className="rounded p-1 text-slate-300 hover:text-red-600"
              aria-label={t('taskExtras.deleteChecklistItem', 'Delete checklist item')}
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <Input
          value={text}
          placeholder={t('taskExtras.addChecklistItem', 'Add a checklist item…')}
          maxLength={500}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && text.trim()) add.mutate()
          }}
        />
        <Button size="sm" onClick={() => add.mutate()} disabled={!text.trim()} loading={add.isPending}>
          {t('common.add', 'Add')}
        </Button>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------- assignees

export function AssigneesEditor({ taskId }: { taskId: string }) {
  const { t } = useI18n()
  const { members } = useOrg()
  const assignees = useTaskAssignees(taskId)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [userId, setUserId] = useState('')
  const [role, setRole] = useState<'assignee' | 'approver'>('assignee')

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.taskAssignees(taskId) })
    void queryClient.invalidateQueries({ queryKey: qk.task(taskId) })
    void queryClient.invalidateQueries({ queryKey: ['orgs'] })
  }

  const set = useMutation({
    mutationFn: (entries: { user_id: string; role: 'assignee' | 'approver' }[]) =>
      checklistApi.setAssignees(taskId, entries),
    onSuccess: invalidate,
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('taskExtras.updateAssigneesError', 'Could not update assignees')),
  })

  const rows = assignees.data ?? []
  const candidates = members.filter(
    (membership) => !rows.some((row) => row.user_id === membership.user_id),
  )

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-slate-800">
        {t('taskExtras.assignees', 'Assignees')}
      </h3>
      <div className="space-y-1">
        {rows.map((row) => (
          <div key={row.user_id} className="flex items-center gap-2 rounded-lg border border-slate-200 px-2 py-1.5">
            <span className="min-w-0 flex-1 truncate text-sm text-slate-700">{row.name}</span>
            <Badge className={row.role === 'approver' ? 'bg-violet-100 text-violet-700' : 'bg-slate-100 text-slate-600'}>
              {row.role === 'approver'
                ? t('taskExtras.roleApprover', 'Approver')
                : t('taskExtras.roleAssignee', 'Assignee')}
            </Badge>
            <button
              type="button"
              onClick={() =>
                set.mutate(
                  rows
                    .filter((entry) => entry.user_id !== row.user_id)
                    .map((entry) => ({ user_id: entry.user_id, role: entry.role })),
                )
              }
              className="rounded p-1 text-slate-300 hover:text-red-600"
              aria-label={t('taskExtras.removeAssignee', 'Remove assignee')}
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <Select value={userId} onChange={(event) => setUserId(event.target.value)}>
          <option value="">{t('taskExtras.addMember', 'Add member…')}</option>
          {candidates.map((membership) => (
            <option key={membership.user_id} value={membership.user_id}>
              {membership.user?.full_name || membership.user?.email || membership.user_id}
            </option>
          ))}
        </Select>
        <Select className="w-auto" value={role} onChange={(event) => setRole(event.target.value as 'assignee' | 'approver')}>
          <option value="assignee">{t('taskExtras.roleAssignee', 'Assignee')}</option>
          <option value="approver">{t('taskExtras.roleApprover', 'Approver')}</option>
        </Select>
        <Button
          size="sm"
          disabled={!userId}
          loading={set.isPending}
          onClick={() => {
            set.mutate([...rows.map((row) => ({ user_id: row.user_id, role: row.role })), { user_id: userId, role }])
            setUserId('')
          }}
        >
          {t('common.add', 'Add')}
        </Button>
      </div>
    </section>
  )
}

// ------------------------------------------------------------- custom fields

export function CustomFieldsEditor({ task }: { task: TaskRead }) {
  const { t } = useI18n()
  const fields = useCustomFields(task.project_id)
  const { members } = useOrg()
  const queryClient = useQueryClient()
  const toast = useToast()

  const patch = useMutation({
    mutationFn: ({ value, key }: { value: unknown; key: string }) =>
      tasksApi.update(task.id, { custom_fields: { [key]: value } }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.task(task.id) })
      void queryClient.invalidateQueries({ queryKey: ['orgs'] })
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('taskExtras.saveValueError', 'Could not save value')),
  })

  const current = new Map(
    task.custom_fields.map((entry) => [entry.field_id, entry.value]),
  )
  const list = fields.data ?? []
  if (list.length === 0) return null

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-slate-800">
        {t('taskExtras.customFields', 'Custom fields')}
      </h3>
      <div className="grid gap-3 sm:grid-cols-2">
        {list.map((field) => {
          const value = current.get(field.id)
          const save = (next: unknown) => patch.mutate({ value: next, key: field.key })
          return (
            <Field key={field.id} label={field.name}>
              {field.field_type === 'select' ? (
                <Select
                  value={typeof value === 'string' ? value : ''}
                  onChange={(event) => save(event.target.value || null)}
                >
                  <option value="">—</option>
                  {field.options.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </Select>
              ) : field.field_type === 'user' ? (
                <Select
                  value={typeof value === 'string' ? value : ''}
                  onChange={(event) => save(event.target.value || null)}
                >
                  <option value="">—</option>
                  {members.map((membership) => (
                    <option key={membership.user_id} value={membership.user_id}>
                      {membership.user?.full_name || membership.user?.email || membership.user_id}
                    </option>
                  ))}
                </Select>
              ) : field.field_type === 'multi_select' ? (
                <div className="flex flex-wrap gap-1.5">
                  {field.options.map((option) => {
                    const selected = Array.isArray(value) && (value as string[]).includes(option)
                    return (
                      <button
                        key={option}
                        type="button"
                        onClick={() => {
                          const listValue = Array.isArray(value) ? [...(value as string[])] : []
                          save(
                            selected
                              ? listValue.filter((entry) => entry !== option)
                              : [...listValue, option],
                          )
                        }}
                        className={
                          selected
                            ? 'rounded-full border border-brand-300 bg-brand-50 px-2 py-0.5 text-[11px] text-brand-700'
                            : 'rounded-full border border-slate-200 px-2 py-0.5 text-[11px] text-slate-500'
                        }
                      >
                        {option}
                      </button>
                    )
                  })}
                </div>
              ) : field.field_type === 'checkbox' ? (
                <Checkbox
                  label=""
                  checked={value === true}
                  onChange={(event) => save(event.target.checked)}
                />
              ) : (
                <Input
                  type={
                    field.field_type === 'number'
                      ? 'number'
                      : field.field_type === 'date'
                        ? 'date'
                        : 'text'
                  }
                  defaultValue={value == null ? '' : String(value)}
                  key={`${field.id}-${String(value)}`}
                  onBlur={(event) => {
                    const raw = event.target.value
                    if (field.field_type === 'number') {
                      save(raw === '' ? null : Number(raw))
                    } else {
                      save(raw === '' ? null : raw)
                    }
                  }}
                />
              )}
            </Field>
          )
        })}
      </div>
    </section>
  )
}

// -------------------------------------------------------------------- links

export function LinksSection({ task }: { task: TaskRead }) {
  const { t } = useI18n()
  const links = useTaskLinks(task.id)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [targetId, setTargetId] = useState('')
  const [linkType, setLinkType] = useState('blocks')

  const candidates = useQuery({
    queryKey: qk.tasks(task.organization_id, { project_id: task.project_id, limit: 100 }),
    queryFn: () => tasksApi.list(task.organization_id, { project_id: task.project_id, limit: 100 }),
  })
  void candidates

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.taskLinks(task.id) })
    void queryClient.invalidateQueries({ queryKey: ['orgs'] })
  }

  const create = useMutation({
    mutationFn: () => linksApi.create(task.id, { to_task_id: targetId, link_type: linkType }),
    onSuccess: () => {
      invalidate()
      setTargetId('')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('taskExtras.createLinkError', 'Could not create link')),
  })
  const remove = useMutation({
    mutationFn: (linkId: string) => linksApi.remove(task.id, linkId),
    onSuccess: invalidate,
  })

  const groups: { label: string; entries: NonNullable<typeof links.data>['blocks'] }[] = [
    { label: t('taskExtras.linkBlocks', 'Blocks'), entries: links.data?.blocks ?? [] },
    { label: t('taskExtras.linkBlockedBy', 'Blocked by'), entries: links.data?.blocked_by ?? [] },
    { label: t('taskExtras.linkRelatesTo', 'Relates to'), entries: links.data?.relates_to ?? [] },
    { label: t('taskExtras.linkDuplicates', 'Duplicates'), entries: links.data?.duplicates ?? [] },
    { label: t('taskExtras.linkClones', 'Clones'), entries: links.data?.clones ?? [] },
  ].filter((group) => group.entries.length > 0)

  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-800">
        <Link2 className="h-3.5 w-3.5" /> {t('taskExtras.links', 'Links & dependencies')}
      </h3>
      {groups.map((group) => (
        <div key={group.label} className="space-y-1">
          <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
            {group.label}
          </p>
          {group.entries.map((entry) => (
            <div key={entry.id} className="flex items-center gap-2 rounded-lg border border-slate-200 px-2 py-1.5">
              {entry.task.key && (
                <span className="font-mono text-[10px] text-slate-400">{entry.task.key}</span>
              )}
              <span className="min-w-0 flex-1 truncate text-sm text-slate-700">
                {entry.task.title}
              </span>
              {entry.task.status_category === 'done' && (
                <Badge className="bg-emerald-100 text-emerald-700">
                  {t('taskExtras.doneBadge', 'done')}
                </Badge>
              )}
              <button
                type="button"
                onClick={() => remove.mutate(entry.id)}
                className="rounded p-1 text-slate-300 hover:text-red-600"
                aria-label={t('taskExtras.removeLink', 'Remove link')}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      ))}
      <div className="flex gap-2">
        <Select value={targetId} onChange={(event) => setTargetId(event.target.value)}>
          <option value="">{t('taskExtras.linkTask', 'Link a task…')}</option>
          {(candidates.data?.items ?? [])
            .filter((entry) => entry.id !== task.id)
            .map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.key ? `${entry.key} · ` : ''}
                {entry.title}
              </option>
            ))}
        </Select>
        <Select className="w-auto" value={linkType} onChange={(event) => setLinkType(event.target.value)}>
          <option value="blocks">{t('taskExtras.linkBlocks', 'Blocks')}</option>
          <option value="relates_to">{t('taskExtras.linkRelatesTo', 'Relates to')}</option>
          <option value="duplicates">{t('taskExtras.linkDuplicates', 'Duplicates')}</option>
          <option value="clones">{t('taskExtras.linkClones', 'Clones')}</option>
        </Select>
        <Button size="sm" disabled={!targetId} loading={create.isPending} onClick={() => create.mutate()}>
          <Plus className="h-3.5 w-3.5" /> {t('taskExtras.linkAction', 'Link')}
        </Button>
      </div>
    </section>
  )
}

// ----------------------------------------------------------------- worklogs

export function WorklogSection({ task }: { task: TaskRead }) {
  const { t } = useI18n()
  const { org } = useOrg()
  const worklogs = useTaskWorklogs(task.id)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [minutes, setMinutes] = useState('30')
  const [startedAt, setStartedAt] = useState(() => new Date().toISOString().slice(0, 16))
  const [description, setDescription] = useState('')

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.taskWorklogs(task.id) })
    void queryClient.invalidateQueries({ queryKey: qk.task(task.id) })
    void queryClient.invalidateQueries({ queryKey: ['orgs'] })
  }

  const add = useMutation({
    mutationFn: () =>
      worklogsApi.create(task.id, {
        minutes: Number(minutes),
        started_at: new Date(startedAt).toISOString(),
        description: description.trim() || null,
      }),
    onSuccess: () => {
      invalidate()
      setDescription('')
      toast.success(t('taskExtras.timeLogged', 'Time logged'))
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('taskExtras.logTimeError', 'Could not log time')),
  })
  const remove = useMutation({
    mutationFn: (worklogId: string) => worklogsApi.remove(org.slug, worklogId),
    onSuccess: invalidate,
  })

  const rows = worklogs.data ?? []
  const total = rows.reduce((sum, row) => sum + row.minutes, 0)

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800">
          {t('taskExtras.timeTracking', 'Time tracking')}
        </h3>
        <span className="text-xs text-slate-400">
          {t('taskExtras.loggedTime', '{hours}h {minutes}m logged', {
            hours: Math.floor(total / 60),
            minutes: total % 60,
          })}
        </span>
      </div>
      {rows.map((row) => (
        <div key={row.id} className="flex items-center gap-2 rounded-lg border border-slate-200 px-2 py-1.5 text-xs">
          <span className="text-slate-500">{formatDateTime(row.started_at)}</span>
          <span className="min-w-0 flex-1 truncate text-slate-700">
            {row.description || row.user_name}
          </span>
          <span className="font-medium text-slate-700">
            {t('taskExtras.duration', '{hours}h {minutes}m', {
              hours: Math.floor(row.minutes / 60),
              minutes: row.minutes % 60,
            })}
          </span>
          <button
            type="button"
            onClick={() => remove.mutate(row.id)}
            className="rounded p-1 text-slate-300 hover:text-red-600"
            aria-label={t('taskExtras.deleteWorklog', 'Delete worklog')}
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      ))}
      <div className="grid gap-2 sm:grid-cols-[90px_1fr_1fr_auto]">
        <Input
          type="number"
          min={1}
          value={minutes}
          onChange={(event) => setMinutes(event.target.value)}
        />
        <Input
          type="datetime-local"
          value={startedAt}
          onChange={(event) => setStartedAt(event.target.value)}
        />
        <Input
          value={description}
          placeholder={t('taskExtras.worklogPlaceholder', 'What did you work on?')}
          maxLength={2000}
          onChange={(event) => setDescription(event.target.value)}
        />
        <Button
          size="sm"
          onClick={() => add.mutate()}
          loading={add.isPending}
          disabled={!minutes || Number(minutes) <= 0}
        >
          {t('taskExtras.logTime', 'Log time')}
        </Button>
      </div>
    </section>
  )
}

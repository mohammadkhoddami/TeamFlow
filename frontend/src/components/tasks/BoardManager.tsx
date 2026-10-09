import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useToast } from '../../contexts/toast'
import { ApiError, workflowsApi } from '../../lib/api'
import { ALL_TASK_TYPES, boardIssueTypes } from '../../lib/boardQuery'
import { qk, useBoards, useWorkflow } from '../../lib/hooks'
import { useI18n } from '../../lib/i18n'
import type { BoardRead, SwimlaneBy, TaskType, WorkflowStatusRead } from '../../lib/types'
import { Button, Checkbox, Field, Input, Modal, Select } from '../ui'

const SWIMLANE_LABELS: Record<SwimlaneBy, string> = {
  none: 'No swimlanes',
  assignee: 'By assignee',
  priority: 'By priority',
  label: 'By label',
}

const TYPE_LABELS: Record<TaskType, string> = {
  epic: 'Epic',
  story: 'Story',
  task: 'Task',
}

interface BoardDraft {
  name: string
  swimlaneBy: SwimlaneBy
  filterQuery: string
  isDefault: boolean
  issueTypes: TaskType[]
  columns: string[]
}

function statusKeys(statuses: WorkflowStatusRead[]): string[] {
  return [...statuses].sort((a, b) => a.position - b.position).map((status) => status.key)
}

function emptyDraft(statuses: WorkflowStatusRead[]): BoardDraft {
  return {
    name: '',
    swimlaneBy: 'none',
    filterQuery: '',
    isDefault: false,
    issueTypes: [...ALL_TASK_TYPES],
    columns: statusKeys(statuses),
  }
}

function draftFromBoard(board: BoardRead, statuses: WorkflowStatusRead[]): BoardDraft {
  const known = new Set(statusKeys(statuses))
  return {
    name: board.name,
    swimlaneBy: board.swimlane_by,
    filterQuery: board.filter_query ?? '',
    isDefault: board.is_default,
    issueTypes: boardIssueTypes(board),
    columns: board.columns?.filter((key) => known.has(key)) ?? statusKeys(statuses),
  }
}

function toPayload(draft: BoardDraft, statuses: WorkflowStatusRead[]) {
  const allTypes = draft.issueTypes.length === ALL_TASK_TYPES.length
  const allColumns = draft.columns.length === statuses.length
  return {
    name: draft.name.trim(),
    swimlane_by: draft.swimlaneBy,
    filter_query: draft.filterQuery.trim() || null,
    // The API treats an empty list as "clear the subset" and normalizes every
    // type to NULL, so use [] on updates to reset a previously saved subset.
    issue_types: allTypes ? [] : draft.issueTypes,
    columns: allColumns ? [] : draft.columns,
    is_default: draft.isDefault,
  }
}

function BoardForm({
  draft,
  statuses,
  onChange,
  nameRequired,
}: {
  draft: BoardDraft
  statuses: WorkflowStatusRead[]
  onChange: (patch: Partial<BoardDraft>) => void
  nameRequired?: boolean
}) {
  const { t } = useI18n()

  const toggle = <T,>(list: T[], value: T): T[] =>
    list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value]

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t('common.name', 'Name')}>
          <Input
            value={draft.name}
            maxLength={128}
            placeholder={nameRequired ? t('board.namePlaceholder', 'Backend board') : undefined}
            onChange={(event) => onChange({ name: event.target.value })}
          />
        </Field>
        <Field label={t('board.swimlanes', 'Swimlanes')}>
          <Select
            value={draft.swimlaneBy}
            onChange={(event) => onChange({ swimlaneBy: event.target.value as SwimlaneBy })}
          >
            <option value="none">{t('board.swimlane.none', 'No swimlanes')}</option>
            <option value="assignee">{t('board.swimlane.assignee', 'By assignee')}</option>
            <option value="priority">{t('board.swimlane.priority', 'By priority')}</option>
            <option value="label">{t('board.swimlane.label', 'By label')}</option>
          </Select>
        </Field>
      </div>

      <div>
        <p className="text-sm font-medium text-slate-700">{t('board.issueTypes', 'Issue types')}</p>
        <p className="mb-1.5 text-[11px] text-slate-400">
          {t('board.issueTypesHint', 'Only the checked issue types appear on this board.')}
        </p>
        <div className="flex flex-wrap gap-3">
          {ALL_TASK_TYPES.map((type) => (
            <Checkbox
              key={type}
              label={t(`type.${type}`, TYPE_LABELS[type])}
              checked={draft.issueTypes.includes(type)}
              onChange={() => onChange({ issueTypes: toggle(draft.issueTypes, type) })}
            />
          ))}
        </div>
        {draft.issueTypes.length === 0 && (
          <p className="mt-1 text-[11px] text-red-600">
            {t('board.needOneType', 'Select at least one issue type')}
          </p>
        )}
      </div>

      <div>
        <p className="text-sm font-medium text-slate-700">
          {t('board.visibleColumns', 'Board columns')}
        </p>
        <p className="mb-1.5 text-[11px] text-slate-400">
          {t('board.columnsHint', 'Only the checked workflow statuses get a column.')}
        </p>
        <div className="flex flex-wrap gap-x-3 gap-y-1.5">
          {[...statuses]
            .sort((a, b) => a.position - b.position)
            .map((status) => (
              <Checkbox
                key={status.key}
                label={status.name}
                checked={draft.columns.includes(status.key)}
                onChange={() => onChange({ columns: toggle(draft.columns, status.key) })}
              />
            ))}
        </div>
        {draft.columns.length === 0 && (
          <p className="mt-1 text-[11px] text-red-600">
            {t('board.needOneColumn', 'Select at least one column')}
          </p>
        )}
      </div>

      <Field
        label={t('board.teamql', 'TeamQL filter')}
        hint={t('board.teamqlHint', 'Optional — e.g. label = backend AND priority = high')}
      >
        <Input
          value={draft.filterQuery}
          placeholder={t('board.teamqlPlaceholder', 'priority = high')}
          onChange={(event) => onChange({ filterQuery: event.target.value })}
        />
      </Field>

      <Checkbox
        label={t('board.makeDefaultCheckbox', 'Make this the default board')}
        checked={draft.isDefault}
        onChange={(event) => onChange({ isDefault: event.target.checked })}
      />
    </div>
  )
}

export function BoardManager({
  projectId,
  slug,
  open,
  onClose,
}: {
  projectId: string
  slug: string
  open: boolean
  onClose: () => void
}) {
  const { t } = useI18n()
  const boards = useBoards(projectId)
  const workflow = useWorkflow(projectId)
  const queryClient = useQueryClient()
  const toast = useToast()
  const [draft, setDraft] = useState<BoardDraft>(() => emptyDraft([]))
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState<BoardDraft>(() => emptyDraft([]))
  const statuses = workflow.data ?? []

  useEffect(() => {
    if (open) {
      setDraft(emptyDraft(workflow.data ?? []))
      setEditingId(null)
    }
  }, [open, workflow.data])

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.boards(projectId) })
    void queryClient.invalidateQueries({ queryKey: ['orgs'] })
  }

  const create = useMutation({
    mutationFn: () =>
      workflowsApi.createBoard(projectId, toPayload(draft, statuses)),
    onSuccess: () => {
      invalidate()
      setDraft(emptyDraft(statuses))
      toast.success(t('board.created', 'Board created'))
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('board.createError', 'Could not create board')),
  })

  const update = useMutation({
    mutationFn: ({ boardId, data }: { boardId: string; data: Parameters<typeof workflowsApi.updateBoard>[2] }) =>
      workflowsApi.updateBoard(slug, boardId, data),
    onSuccess: () => {
      invalidate()
      toast.success(t('board.updated', 'Board updated'))
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('board.updateError', 'Could not update board')),
  })

  const remove = useMutation({
    mutationFn: (boardId: string) => workflowsApi.removeBoard(slug, boardId),
    onSuccess: () => {
      invalidate()
      toast.success(t('board.deleted', 'Board deleted'))
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : t('board.deleteError', 'Could not delete board')),
  })

  const patchDraft = (patch: Partial<BoardDraft>) =>
    setDraft((current) => ({ ...current, ...patch }))
  const patchEditDraft = (patch: Partial<BoardDraft>) =>
    setEditDraft((current) => ({ ...current, ...patch }))

  const draftValid =
    draft.name.trim().length > 0 && draft.issueTypes.length > 0 && draft.columns.length > 0
  const editValid =
    editDraft.name.trim().length > 0 &&
    editDraft.issueTypes.length > 0 &&
    editDraft.columns.length > 0

  const boardSummary = (board: BoardRead) => {
    const types = boardIssueTypes(board)
    const allTypes = types.length === ALL_TASK_TYPES.length
    const typeNames = types.map((type) => t(`type.${type}`, TYPE_LABELS[type]))
    const visible = board.columns
      ? statuses.filter((status) => board.columns?.includes(status.key))
      : []
    const allColumns = !board.columns || board.columns.length === 0 || visible.length === statuses.length
    const columnNames = visible.map((status) => status.name)
    return [
      t('board.typesValue', 'Issue types: {value}', {
        value: allTypes
          ? t('board.allIssueTypes', 'All issue types')
          : typeNames.join(', '),
      }),
      t('board.columnsValue', 'Columns: {value}', {
        value: allColumns ? t('board.allColumns', 'All columns') : columnNames.join(', '),
      }),
    ]
  }

  return (
    <Modal open={open} onClose={onClose} title={t('board.title', 'Boards')} size="lg">
      <div className="space-y-5">
        <section className="space-y-2">
          {(boards.data ?? []).map((board) => (
            <div key={board.id} className="rounded-lg border border-slate-200">
              <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-medium text-slate-800">{board.name}</p>
                    {board.is_default && (
                      <span className="rounded-full bg-brand-50 px-1.5 py-0.5 text-[10px] text-brand-700">
                          {t('board.defaultBadge', 'default')}
                        </span>
                    )}
                  </div>
                  {boardSummary(board).map((line) => (
                    <p key={line} className="text-[11px] text-slate-400">
                      {line}
                    </p>
                  ))}
                  <p className="text-[11px] text-slate-400">
                    {t('board.swimlanesValue', 'Swimlanes: {value}', {
                      value: t(
                        `board.swimlane.${board.swimlane_by}`,
                        SWIMLANE_LABELS[board.swimlane_by],
                      ),
                    })}
                    {board.filter_query
                      ? t('board.filterSuffix', ' · filter: {query}', {
                          query: board.filter_query,
                        })
                      : ''}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      setEditDraft(draftFromBoard(board, statuses))
                      setEditingId(editingId === board.id ? null : board.id)
                    }}
                  >
                    <Pencil className="h-3.5 w-3.5" /> {t('board.editBoard', 'Edit')}
                  </Button>
                  {!board.is_default && (
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => update.mutate({ boardId: board.id, data: { is_default: true } })}
                    >
                      {t('board.makeDefault', 'Make default')}
                    </Button>
                  )}
                  <button
                    type="button"
                    onClick={() => remove.mutate(board.id)}
                    className="rounded p-1.5 text-slate-300 hover:bg-red-50 hover:text-red-600"
                    title={t('board.deleteBoard', 'Delete board')}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              {editingId === board.id && (
                <div className="space-y-3 border-t border-slate-100 bg-slate-50/60 px-3 py-3">
                  <BoardForm
                    draft={editDraft}
                    statuses={statuses}
                    onChange={patchEditDraft}
                  />
                  <div className="flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => setEditingId(null)}
                    >
                      {t('common.cancel', 'Cancel')}
                    </Button>
                    <Button
                      size="sm"
                      loading={update.isPending}
                      disabled={!editValid}
                      onClick={() =>
                        update.mutate(
                          { boardId: board.id, data: toPayload(editDraft, statuses) },
                          { onSuccess: () => setEditingId(null) },
                        )
                      }
                    >
                      {t('board.saveBoard', 'Save board')}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          ))}
          {(boards.data ?? []).length === 0 && (
            <p className="rounded-lg border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400">
              {t(
                'board.empty',
                'No saved boards yet — the project uses the default board view. Create one below to choose its issue types, columns and filters.',
              )}
            </p>
          )}
        </section>

        <section className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <p className="text-sm font-semibold text-slate-800">
            {t('board.newBoard', 'New board')}
          </p>
          <BoardForm
            draft={draft}
            statuses={statuses}
            onChange={patchDraft}
            nameRequired
          />
          <p className="text-[11px] text-slate-400">
            {t('board.columnsFollow', 'Workflow statuses: {count}', {
              count: statuses.length,
            })}
          </p>
          <Button
            onClick={() => create.mutate()}
            loading={create.isPending}
            disabled={!draftValid}
          >
            <Plus className="h-4 w-4" /> {t('board.create', 'Create board')}
          </Button>
        </section>
      </div>
    </Modal>
  )
}

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useToast } from '../../contexts/toast'
import { ApiError, workflowsApi } from '../../lib/api'
import { qk, useBoards, useWorkflow } from '../../lib/hooks'
import { useI18n } from '../../lib/i18n'
import type { SwimlaneBy } from '../../lib/types'
import { Button, Checkbox, Field, Input, Modal, Select } from '../ui'

const SWIMLANE_LABELS: Record<SwimlaneBy, string> = {
  none: 'No swimlanes',
  assignee: 'By assignee',
  priority: 'By priority',
  label: 'By label',
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
  const [name, setName] = useState('')
  const [swimlaneBy, setSwimlaneBy] = useState<SwimlaneBy>('none')
  const [filterQuery, setFilterQuery] = useState('')
  const [isDefault, setIsDefault] = useState(false)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.boards(projectId) })
    void queryClient.invalidateQueries({ queryKey: ['orgs'] })
  }

  const create = useMutation({
    mutationFn: () =>
      workflowsApi.createBoard(projectId, {
        name: name.trim(),
        swimlane_by: swimlaneBy,
        filter_query: filterQuery.trim() || null,
        is_default: isDefault,
      }),
    onSuccess: () => {
      invalidate()
      setName('')
      setFilterQuery('')
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

  return (
    <Modal open={open} onClose={onClose} title={t('board.title', 'Boards')} size="lg">
      <div className="space-y-5">
        <section className="space-y-2">
          {(boards.data ?? []).map((board) => (
            <div
              key={board.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2.5"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <p className="truncate text-sm font-medium text-slate-800">{board.name}</p>
                  {board.is_default && (
                    <span className="rounded-full bg-brand-50 px-1.5 py-0.5 text-[10px] text-brand-700">
                        {t('board.defaultBadge', 'default')}
                      </span>
                  )}
                </div>
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
                <Select
                  className="w-auto"
                  value={board.swimlane_by}
                  onChange={(event) =>
                    update.mutate({
                      boardId: board.id,
                      data: { swimlane_by: event.target.value },
                    })
                  }
                >
                  <option value="none">{t('board.swimlane.none', 'No swimlanes')}</option>
                  <option value="assignee">
                    {t('board.swimlane.assignee', 'By assignee')}
                  </option>
                  <option value="priority">
                    {t('board.swimlane.priority', 'By priority')}
                  </option>
                  <option value="label">{t('board.swimlane.label', 'By label')}</option>
                </Select>
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
          ))}
          {(boards.data ?? []).length === 0 && (
            <p className="rounded-lg border border-dashed border-slate-200 px-3 py-6 text-center text-xs text-slate-400">
              {t(
                'board.empty',
                'No saved boards yet — the project uses the default board view. Create one below to add a TeamQL filter or swimlanes.',
              )}
            </p>
          )}
        </section>

        <section className="space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
          <p className="text-sm font-semibold text-slate-800">
            {t('board.newBoard', 'New board')}
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('common.name', 'Name')}>
              <Input
                value={name}
                maxLength={128}
                placeholder={t('board.namePlaceholder', 'Backend board')}
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Field label={t('board.swimlanes', 'Swimlanes')}>
              <Select
                value={swimlaneBy}
                onChange={(event) => setSwimlaneBy(event.target.value as SwimlaneBy)}
              >
                <option value="none">{t('common.none', 'None')}</option>
                <option value="assignee">{t('board.swimlane.assignee', 'By assignee')}</option>
                <option value="priority">{t('board.swimlane.priority', 'By priority')}</option>
                <option value="label">{t('board.swimlane.label', 'By label')}</option>
              </Select>
            </Field>
          </div>
          <Field
            label={t('board.teamql', 'TeamQL filter')}
            hint={t('board.teamqlHint', 'Optional — e.g. label = backend AND status != done')}
          >
            <Input
              value={filterQuery}
              placeholder={t('board.teamqlPlaceholder', 'priority = high')}
              onChange={(event) => setFilterQuery(event.target.value)}
            />
          </Field>
          <Checkbox
            label={t('board.makeDefaultCheckbox', 'Make this the default board')}
            checked={isDefault}
            onChange={(event) => setIsDefault(event.target.checked)}
          />
          <p className="text-[11px] text-slate-400">
            {t('board.columnsFollow', 'Columns follow the project workflow ({count} statuses).', {
              count: workflow.data?.length ?? 0,
            })}
          </p>
          <Button
            onClick={() => create.mutate()}
            loading={create.isPending}
            disabled={!name.trim()}
          >
            <Plus className="h-4 w-4" /> {t('board.create', 'Create board')}
          </Button>
        </section>
      </div>
    </Modal>
  )
}

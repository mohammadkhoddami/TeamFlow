import type { BoardRead, TaskType, WorkflowStatusRead } from './types'

export const ALL_TASK_TYPES: TaskType[] = ['epic', 'story', 'task']

export type BoardSettings = Pick<BoardRead, 'filter_query' | 'columns' | 'issue_types'>

export function boardVisibleStatuses(
  workflow: WorkflowStatusRead[],
  board?: BoardSettings | null,
): WorkflowStatusRead[] {
  const ordered = [...workflow].sort((a, b) => a.position - b.position)
  if (!board?.columns || board.columns.length === 0) return ordered
  const visible = new Set(board.columns)
  return ordered.filter((status) => visible.has(status.key))
}

export function boardIssueTypes(board?: BoardSettings | null): TaskType[] {
  if (!board?.issue_types || board.issue_types.length === 0) return [...ALL_TASK_TYPES]
  return board.issue_types
}

export interface BoardQueryInput {
  projectId: string
  board: BoardSettings
  /** '' = every task, '__backlog__' = sprintless, otherwise a sprint UUID. */
  sprintFilter?: string
}

/**
 * Builds a project-scoped TeamQL query for a saved board, combining its issue
 * type / column subsets, its advanced filter and the sprint selector. Values
 * are enums, workflow keys and UUIDs, so no quoting is required.
 */
export function buildBoardQuery({
  projectId,
  board,
  sprintFilter = '',
}: BoardQueryInput): string {
  const conditions = [`project = ${projectId}`]

  const types = boardIssueTypes(board)
  if (types.length < ALL_TASK_TYPES.length) {
    conditions.push(`type in (${types.join(', ')})`)
  }
  if (board.columns && board.columns.length > 0) {
    conditions.push(`status in (${board.columns.join(', ')})`)
  }
  if (sprintFilter === '__backlog__') {
    conditions.push('sprint is empty')
  } else if (sprintFilter) {
    conditions.push(`sprint = ${sprintFilter}`)
  }

  const extra = board.filter_query?.trim()
  if (extra) conditions.push(extra)

  return conditions.join(' AND ')
}

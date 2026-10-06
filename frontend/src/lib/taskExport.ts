import { PRIORITY_LABELS, STATUS_LABELS, TYPE_LABELS, type TaskRead, type TaskStatus } from './types'
import { formatDate } from './utils'

const OPEN_STATUSES: readonly TaskStatus[] = ['todo', 'in_progress', 'in_review']

const EXPORT_FILENAME = 'opening-tasks.md'

function escapeText(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/([*_`[\]])/g, '\\$1').replace(/\s+/g, ' ').trim()
}

function taskLine(task: TaskRead): string {
  const details = [TYPE_LABELS[task.type], PRIORITY_LABELS[task.priority]]
  details.push(
    task.assignee
      ? `assigned to ${task.assignee.full_name || task.assignee.email}`
      : 'unassigned',
  )
  if (task.due_date) details.push(`due ${formatDate(task.due_date)}`)
  if (task.labels.length > 0) {
    details.push(`labels: ${task.labels.map((label) => label.name).join(', ')}`)
  }
  if (task.parent) details.push(`parent: ${task.parent.title}`)
  return `- [ ] **${escapeText(task.title)}** — ${details.map(escapeText).join(' · ')}`
}

export function buildOpenTasksMarkdown(projectName: string, tasks: TaskRead[]): string {
  const open = tasks.filter((task) => task.status !== 'done')
  const lines = [
    `# Opening tasks — ${escapeText(projectName)}`,
    '',
    `_Exported ${formatDate(new Date().toISOString())} · ${open.length} open task${
      open.length === 1 ? '' : 's'
    }_`,
  ]
  for (const status of OPEN_STATUSES) {
    const column = open.filter((task) => task.status === status)
    if (column.length === 0) continue
    lines.push('', `## ${STATUS_LABELS[status]} (${column.length})`, '')
    lines.push(...column.map(taskLine))
  }
  if (open.length === 0) lines.push('', '_No open tasks._')
  return `${lines.join('\n')}\n`
}

export function downloadOpenTasksMarkdown(projectName: string, tasks: TaskRead[]): number {
  const open = tasks.filter((task) => task.status !== 'done')
  const blob = new Blob([buildOpenTasksMarkdown(projectName, tasks)], {
    type: 'text/markdown;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = EXPORT_FILENAME
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
  return open.length
}

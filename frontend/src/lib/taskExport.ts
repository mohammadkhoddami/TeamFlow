import { getStoredLocale, translate, type TranslationVars } from './i18n'
import { PRIORITY_LABELS, STATUS_LABELS, TYPE_LABELS, type TaskRead, type TaskStatus } from './types'
import { formatDate } from './utils'

const OPEN_STATUSES: readonly TaskStatus[] = ['todo', 'in_progress', 'in_review']

const EXPORT_FILENAME = 'opening-tasks.md'

function tr(key: string, fallback: string, vars?: TranslationVars): string {
  return translate(getStoredLocale(), key, fallback, vars)
}

function escapeText(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/([*_`[\]])/g, '\\$1').replace(/\s+/g, ' ').trim()
}

function taskLine(task: TaskRead): string {
  const details = [
    tr(`type.${task.type}`, TYPE_LABELS[task.type]),
    tr(`priority.${task.priority}`, PRIORITY_LABELS[task.priority]),
  ]
  details.push(
    task.assignee
      ? tr('tasks.exportAssignedTo', 'assigned to {name}', {
          name: task.assignee.full_name || task.assignee.email,
        })
      : tr('tasks.exportUnassigned', 'unassigned'),
  )
  if (task.due_date) {
    details.push(tr('tasks.exportDue', 'due {date}', { date: formatDate(task.due_date) }))
  }
  if (task.labels.length > 0) {
    details.push(
      tr('tasks.exportLabels', 'labels: {labels}', {
        labels: task.labels.map((label) => label.name).join(', '),
      }),
    )
  }
  if (task.parent) {
    details.push(tr('tasks.exportParent', 'parent: {title}', { title: task.parent.title }))
  }
  return `- [ ] **${escapeText(task.title)}** — ${details.map(escapeText).join(' · ')}`
}

export function buildOpenTasksMarkdown(projectName: string, tasks: TaskRead[]): string {
  const open = tasks.filter((task) => task.status !== 'done')
  const summary =
    open.length === 1
      ? tr('tasks.exportSummaryOne', 'Exported {date} · {count} open task', {
          date: formatDate(new Date().toISOString()),
          count: open.length,
        })
      : tr('tasks.exportSummary', 'Exported {date} · {count} open tasks', {
          date: formatDate(new Date().toISOString()),
          count: open.length,
        })
  const lines = [
    `# ${tr('tasks.exportTitle', 'Opening tasks — {project}', {
      project: escapeText(projectName),
    })}`,
    '',
    `_${summary}_`,
  ]
  for (const status of OPEN_STATUSES) {
    const column = open.filter((task) => task.status === status)
    if (column.length === 0) continue
    lines.push('', `## ${tr(`status.${status}`, STATUS_LABELS[status])} (${column.length})`, '')
    lines.push(...column.map(taskLine))
  }
  if (open.length === 0) lines.push('', `_${tr('tasks.exportNoOpen', 'No open tasks.')}_`)
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

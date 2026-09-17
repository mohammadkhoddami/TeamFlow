import {
  AlertTriangle,
  CheckCircle2,
  FolderKanban,
  ListTodo,
  UserRoundX,
  Users,
} from 'lucide-react'

import { useOrg } from '../components/OrgLayout'
import { Card, CardHeader, ErrorState, PageSpinner } from '../components/ui'
import { useDashboard } from '../lib/hooks'
import { STATUS_LABELS, TASK_STATUSES } from '../lib/types'
import { avatarColor, initials } from '../lib/utils'

export function DashboardPage() {
  const { org } = useOrg()
  const dashboard = useDashboard(org.slug)

  if (dashboard.isLoading) return <PageSpinner label="Crunching numbers…" />
  if (dashboard.isError || !dashboard.data) {
    return (
      <div className="p-6">
        <ErrorState
          message="Could not load dashboard statistics."
          onRetry={() => void dashboard.refetch()}
        />
      </div>
    )
  }

  const stats = dashboard.data
  const byStatus = stats.tasks_by_status
  const maxStatus = Math.max(1, ...TASK_STATUSES.map((status) => byStatus[status]))
  const maxMember = Math.max(1, ...stats.tasks_per_member.map((member) => member.open_tasks))

  const cards = [
    { label: 'Active projects', value: stats.active_projects, hint: `${stats.projects} total`, icon: FolderKanban, tone: 'bg-brand-50 text-brand-700' },
    { label: 'Total tasks', value: stats.total_tasks, hint: `${stats.completed_tasks} completed`, icon: ListTodo, tone: 'bg-sky-50 text-sky-700' },
    { label: 'Overdue', value: stats.overdue_tasks, hint: 'past due date', icon: AlertTriangle, tone: 'bg-red-50 text-red-700' },
    { label: 'Unassigned', value: stats.unassigned_tasks, hint: 'open tasks', icon: UserRoundX, tone: 'bg-amber-50 text-amber-700' },
    { label: 'Active members', value: stats.active_members, hint: 'with a seat', icon: Users, tone: 'bg-emerald-50 text-emerald-700' },
    { label: 'Completion', value: stats.total_tasks ? `${Math.round((stats.completed_tasks / stats.total_tasks) * 100)}%` : '—', hint: 'of all tasks', icon: CheckCircle2, tone: 'bg-violet-50 text-violet-700' },
  ]

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Dashboard</h1>
        <p className="text-sm text-slate-500">Live overview of {org.name}.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {cards.map((card) => (
          <Card key={card.label} className="flex items-center gap-4 p-4">
            <span className={`flex h-10 w-10 items-center justify-center rounded-lg ${card.tone}`}>
              <card.icon className="h-5 w-5" />
            </span>
            <div>
              <p className="text-2xl font-semibold text-slate-900">{card.value}</p>
              <p className="text-xs text-slate-500">
                {card.label} · {card.hint}
              </p>
            </div>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Tasks by status" description="Across every project in this workspace." />
          <div className="space-y-3 p-5">
            {TASK_STATUSES.map((status) => (
              <div key={status}>
                <div className="mb-1 flex items-center justify-between text-xs text-slate-600">
                  <span>{STATUS_LABELS[status]}</span>
                  <span className="font-medium">{byStatus[status]}</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                  <div
                    className="h-full rounded-full bg-brand-500"
                    style={{ width: `${(byStatus[status] / maxStatus) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <CardHeader title="Open tasks per member" description="Who is carrying the load." />
          <div className="space-y-3 p-5">
            {stats.tasks_per_member.length === 0 && (
              <p className="text-sm text-slate-500">No open tasks assigned yet.</p>
            )}
            {stats.tasks_per_member.map((member) => (
              <div key={member.user_id} className="flex items-center gap-3">
                <span
                  className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold text-white ${avatarColor(member.user_id)}`}
                >
                  {initials(member.full_name || '?')}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                    <span className="truncate text-slate-700">
                      {member.full_name || 'Unnamed member'}
                    </span>
                    <span className="font-medium text-slate-600">{member.open_tasks}</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                    <div
                      className="h-full rounded-full bg-emerald-500"
                      style={{ width: `${(member.open_tasks / maxMember) * 100}%` }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  )
}

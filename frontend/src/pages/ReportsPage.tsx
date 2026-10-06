import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { useOrg } from '../components/OrgLayout'
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  Field,
  Input,
  PageSpinner,
  Select,
} from '../components/ui'
import { useToast } from '../contexts/toast'
import { ApiError, capacityApi, reportsApi } from '../lib/api'
import { useProjects, useSprints } from '../lib/hooks'
import type { CapacityMemberRead } from '../lib/types'
import { cn } from '../lib/utils'

const TABS = [
  { key: 'velocity', label: 'Velocity' },
  { key: 'burndown', label: 'Burndown' },
  { key: 'flow', label: 'Cumulative flow' },
  { key: 'cycle', label: 'Cycle & lead time' },
  { key: 'sprint', label: 'Sprint report' },
  { key: 'capacity', label: 'Capacity' },
] as const

type TabKey = (typeof TABS)[number]['key']

export function ReportsPage() {
  const { org } = useOrg()
  const projects = useProjects(org.slug)
  const [projectId, setProjectId] = useState('')
  const [tab, setTab] = useState<TabKey>('velocity')
  const activeProject = projectId || projects.data?.[0]?.id || ''
  const sprints = useSprints(activeProject || undefined)
  const [sprintId, setSprintId] = useState('')

  const sprintOptions = sprints.data ?? []
  const activeSprint =
    sprintId || sprintOptions.find((sprint) => sprint.state === 'active')?.id || sprintOptions[0]?.id || ''

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Reports</h1>
          <p className="text-sm text-slate-500">
            Burndown, velocity, flow and cycle time per project.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            className="w-auto"
            value={activeProject}
            onChange={(event) => {
              setProjectId(event.target.value)
              setSprintId('')
            }}
          >
            {(projects.data ?? []).map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </Select>
          {(tab === 'burndown' || tab === 'sprint') && (
            <Select
              className="w-auto"
              value={activeSprint}
              onChange={(event) => setSprintId(event.target.value)}
            >
              <option value="">Select sprint…</option>
              {sprintOptions.map((sprint) => (
                <option key={sprint.id} value={sprint.id}>
                  {sprint.name} ({sprint.state})
                </option>
              ))}
            </Select>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setTab(entry.key)}
            className={cn(
              'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
              tab === entry.key
                ? 'border-brand-300 bg-brand-50 text-brand-700'
                : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300',
            )}
          >
            {entry.label}
          </button>
        ))}
      </div>

      {!activeProject && <EmptyState title="No project" description="Create a project first." />}
      {activeProject && tab === 'velocity' && <VelocityPanel projectId={activeProject} />}
      {activeProject && tab === 'burndown' && (
        <BurndownPanel projectId={activeProject} sprintId={activeSprint} />
      )}
      {activeProject && tab === 'flow' && <FlowPanel projectId={activeProject} />}
      {activeProject && tab === 'cycle' && <CyclePanel projectId={activeProject} />}
      {activeProject && tab === 'sprint' && (
        <SprintReportPanel sprintId={activeSprint} />
      )}
      {activeProject && tab === 'capacity' && (
        <CapacityPanel sprintId={activeSprint} />
      )}
    </div>
  )
}

function VelocityPanel({ projectId }: { projectId: string }) {
  const report = useQuery({
    queryKey: ['reports', projectId, 'velocity'],
    queryFn: () => reportsApi.velocity(projectId),
  })
  if (report.isLoading) return <PageSpinner />
  if (!report.data) return null
  const max = Math.max(
    1,
    ...report.data.sprints.flatMap((sprint) => [
      sprint.committed_points,
      sprint.completed_points,
    ]),
  )
  return (
    <Card>
      <CardHeader
        title="Velocity"
        description={`Average completed points per sprint: ${report.data.average_completed_points}`}
      />
      <div className="space-y-3 p-5">
        {report.data.sprints.length === 0 && (
          <p className="text-xs text-slate-400">No started or completed sprints yet.</p>
        )}
        {report.data.sprints.map((sprint) => (
          <div key={sprint.sprint_id} className="space-y-1">
            <div className="flex items-center justify-between text-xs text-slate-500">
              <span className="font-medium text-slate-700">{sprint.sprint_name}</span>
              <span>
                {sprint.completed_points} / {sprint.committed_points} pts ·{' '}
                {sprint.completed_tasks}/{sprint.committed_tasks} tasks
              </span>
            </div>
            <div className="h-3 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-brand-400"
                style={{ width: `${(sprint.committed_points / max) * 100}%` }}
              />
            </div>
            <div className="h-3 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-emerald-500"
                style={{ width: `${(sprint.completed_points / max) * 100}%` }}
              />
            </div>
          </div>
        ))}
        <p className="text-[11px] text-slate-400">
          Grey = committed points, green = completed points.
        </p>
      </div>
    </Card>
  )
}

function LineChart({
  series,
  max,
}: {
  series: { label: string; points: number[]; color: string }[]
  max: number
}) {
  const width = 640
  const height = 180
  const count = Math.max(1, series[0]?.points.length ?? 1)
  const path = (points: number[]) =>
    points
      .map((value, index) => {
        const x = (index / Math.max(1, count - 1)) * width
        const y = height - (value / Math.max(1, max)) * (height - 20)
        return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
      })
      .join(' ')
  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-44 w-full min-w-[480px]">
        {[0.25, 0.5, 0.75, 1].map((fraction) => (
          <line
            key={fraction}
            x1={0}
            x2={width}
            y1={height * fraction}
            y2={height * fraction}
            className="stroke-slate-200"
            strokeDasharray="3 4"
          />
        ))}
        {series.map((entry) => (
          <path
            key={entry.label}
            d={path(entry.points)}
            fill="none"
            stroke={entry.color}
            strokeWidth={2}
          />
        ))}
      </svg>
      <div className="mt-1 flex gap-3 text-[11px] text-slate-500">
        {series.map((entry) => (
          <span key={entry.label} className="inline-flex items-center gap-1">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: entry.color }} />
            {entry.label}
          </span>
        ))}
      </div>
    </div>
  )
}

function BurndownPanel({ projectId, sprintId }: { projectId: string; sprintId: string }) {
  const report = useQuery({
    queryKey: ['reports', projectId, 'burndown', sprintId],
    queryFn: () => reportsApi.burndown(projectId, sprintId),
    enabled: Boolean(sprintId),
  })
  if (!sprintId) return <p className="text-xs text-slate-400">Select a sprint.</p>
  if (report.isLoading) return <PageSpinner />
  if (!report.data) return null
  const max = Math.max(
    1,
    report.data.total_points,
    ...report.data.points.map((point) => point.remaining_points),
  )
  return (
    <Card>
      <CardHeader
        title={`Burndown — ${report.data.sprint_name}`}
        description={`${report.data.total_points} points across ${report.data.total_tasks} tasks`}
      />
      <div className="p-5">
        <LineChart
          max={max}
          series={[
            {
              label: 'Remaining points',
              color: '#4f46e5',
              points: report.data.points.map((point) => point.remaining_points),
            },
            {
              label: 'Ideal',
              color: '#94a3b8',
              points: report.data.points.map((point) => point.ideal_points ?? 0),
            },
          ]}
        />
      </div>
    </Card>
  )
}

function FlowPanel({ projectId }: { projectId: string }) {
  const [days, setDays] = useState(30)
  const report = useQuery({
    queryKey: ['reports', projectId, 'cfd', days],
    queryFn: () => reportsApi.cumulativeFlow(projectId, days),
  })
  if (report.isLoading) return <PageSpinner />
  if (!report.data) return null
  const max = Math.max(
    1,
    ...report.data.points.map(
      (point) => point.todo + point.in_progress + point.in_review + point.done,
    ),
  )
  const colors: Record<string, string> = {
    todo: '#cbd5e1',
    in_progress: '#0ea5e9',
    in_review: '#f59e0b',
    done: '#10b981',
  }
  return (
    <Card>
      <CardHeader
        title="Cumulative flow"
        description="Tasks by workflow category per day (history-aware after M2)"
      />
      <div className="space-y-3 p-5">
        <Field label="Window (days)">
          <Input
            type="number"
            min={7}
            max={90}
            value={days}
            onChange={(event) => setDays(Number(event.target.value) || 30)}
          />
        </Field>
        <div className="flex h-44 items-end gap-[2px] overflow-x-auto">
          {report.data.points.map((point) => (
            <div
              key={point.day}
              className="flex min-w-[6px] flex-1 flex-col justify-end"
              title={`${point.day}: ${point.todo} todo, ${point.in_progress} in progress, ${point.in_review} review, ${point.done} done`}
            >
              {(['done', 'in_review', 'in_progress', 'todo'] as const).map((category) => (
                <div
                  key={category}
                  style={{
                    height: `${(point[category] / max) * 160}px`,
                    backgroundColor: colors[category],
                  }}
                />
              ))}
            </div>
          ))}
        </div>
        <div className="flex gap-3 text-[11px] text-slate-500">
          {Object.entries(colors).map(([category, color]) => (
            <span key={category} className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
              {category}
            </span>
          ))}
        </div>
      </div>
    </Card>
  )
}

function CyclePanel({ projectId }: { projectId: string }) {
  const [days, setDays] = useState(30)
  const report = useQuery({
    queryKey: ['reports', projectId, 'cycle', days],
    queryFn: () => reportsApi.cycleTime(projectId, days),
  })
  if (report.isLoading) return <PageSpinner />
  if (!report.data) return null
  const data = report.data
  return (
    <Card>
      <CardHeader
        title="Cycle & lead time"
        description={`${data.count} tasks completed in the last ${data.days} days`}
      />
      <div className="space-y-4 p-5">
        <Field label="Window (days)">
          <Input
            type="number"
            min={7}
            max={90}
            value={days}
            onChange={(event) => setDays(Number(event.target.value) || 30)}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            { label: 'Avg lead', value: data.avg_lead_time_days },
            { label: 'P50 lead', value: data.p50_lead_time_days },
            { label: 'P85 lead', value: data.p85_lead_time_days },
            { label: 'Avg cycle', value: data.avg_cycle_time_days },
            { label: 'P50 cycle', value: data.p50_cycle_time_days },
            { label: 'P85 cycle', value: data.p85_cycle_time_days },
          ].map((entry) => (
            <div key={entry.label} className="rounded-lg border border-slate-200 px-3 py-2">
              <p className="text-[11px] uppercase tracking-wide text-slate-400">{entry.label}</p>
              <p className="text-lg font-semibold text-slate-800">
                {entry.value == null ? '—' : `${entry.value}d`}
              </p>
            </div>
          ))}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 font-medium">Task</th>
                <th className="px-3 py-2 font-medium">Lead (d)</th>
                <th className="px-3 py-2 font-medium">Cycle (d)</th>
              </tr>
            </thead>
            <tbody>
              {data.items.slice(0, 50).map((item) => (
                <tr key={item.task_id} className="border-t border-slate-100">
                  <td className="px-3 py-2">
                    {item.key && <span className="mr-1 font-mono text-[10px] text-slate-400">{item.key}</span>}
                    {item.title}
                  </td>
                  <td className="px-3 py-2 text-slate-500">{item.lead_time_days}</td>
                  <td className="px-3 py-2 text-slate-500">{item.cycle_time_days ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  )
}

function SprintReportPanel({ sprintId }: { sprintId: string }) {
  const report = useQuery({
    queryKey: ['reports', 'sprint', sprintId],
    queryFn: () => reportsApi.sprintReport(sprintId),
    enabled: Boolean(sprintId),
  })
  if (!sprintId) return <p className="text-xs text-slate-400">Select a sprint.</p>
  if (report.isLoading) return <PageSpinner />
  if (!report.data) return null
  const data = report.data
  return (
    <Card>
      <CardHeader title={`Sprint report — ${data.sprint_name}`} description={`State: ${data.state}`} />
      <div className="space-y-4 p-5">
        <div className="grid gap-3 sm:grid-cols-3">
          {[
            { label: 'Committed', value: `${data.committed_tasks} tasks / ${data.committed_points} pts` },
            { label: 'Completed', value: `${data.completed_tasks} tasks / ${data.completed_points} pts` },
            { label: 'Carried over', value: String(data.carried_over) },
            { label: 'Added during sprint', value: String(data.added_during_sprint) },
            { label: 'Scope change', value: `${data.scope_change_pct}%` },
            { label: 'Members', value: String(data.members.length) },
          ].map((entry) => (
            <div key={entry.label} className="rounded-lg border border-slate-200 px-3 py-2">
              <p className="text-[11px] uppercase tracking-wide text-slate-400">{entry.label}</p>
              <p className="text-sm font-semibold text-slate-800">{entry.value}</p>
            </div>
          ))}
        </div>
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2 font-medium">Member</th>
              <th className="px-3 py-2 font-medium">Assigned</th>
              <th className="px-3 py-2 font-medium">Completed</th>
              <th className="px-3 py-2 font-medium">Points</th>
            </tr>
          </thead>
          <tbody>
            {data.members.map((member) => (
              <tr key={member.user_id ?? 'unassigned'} className="border-t border-slate-100">
                <td className="px-3 py-2">{member.name || 'Unassigned'}</td>
                <td className="px-3 py-2 text-slate-500">{member.assigned_tasks}</td>
                <td className="px-3 py-2 text-slate-500">{member.completed_tasks}</td>
                <td className="px-3 py-2 text-slate-500">{member.completed_points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function CapacityPanel({ sprintId }: { sprintId: string }) {
  const toast = useToast()
  const [draft, setDraft] = useState<Record<string, string>>({})
  const capacity = useQuery({
    queryKey: ['reports', 'capacity', sprintId],
    queryFn: () => capacityApi.get(sprintId),
    enabled: Boolean(sprintId),
  })

  const save = useMutation({
    mutationFn: () =>
      capacityApi.set(
        sprintId,
        (capacity.data ?? []).map((member: CapacityMemberRead) => ({
          user_id: member.user_id,
          capacity:
            draft[member.user_id] !== undefined
              ? draft[member.user_id] === ''
                ? null
                : Number(draft[member.user_id])
              : member.capacity,
          note: member.note,
        })),
      ),
    onSuccess: () => {
      void capacity.refetch()
      setDraft({})
      toast.success('Capacity saved')
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not save capacity'),
  })

  if (!sprintId) return <p className="text-xs text-slate-400">Select a sprint.</p>
  if (capacity.isLoading) return <PageSpinner />
  return (
    <Card>
      <CardHeader
        title="Capacity planning"
        description="Set each member's points budget; overloaded rows are highlighted."
      />
      <div className="space-y-3 p-5">
        {(capacity.data ?? []).map((member) => {
          const value =
            draft[member.user_id] !== undefined
              ? draft[member.user_id]
              : member.capacity == null
                ? ''
                : String(member.capacity)
          return (
            <div
              key={member.user_id}
              className={cn(
                'flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2',
                member.overloaded ? 'border-red-300 bg-red-50' : 'border-slate-200',
              )}
            >
              <span className="min-w-0 flex-1 truncate text-sm text-slate-700">
                {member.name}
              </span>
              <span className="text-xs text-slate-500">
                {member.assigned_tasks} tasks · {member.assigned_points} pts assigned ·{' '}
                {member.completed_points} pts done
              </span>
              <div className="flex items-center gap-2">
                <Input
                  className="w-24"
                  type="number"
                  min={0}
                  placeholder="—"
                  value={value}
                  onChange={(event) =>
                    setDraft((current) => ({ ...current, [member.user_id]: event.target.value }))
                  }
                />
                {member.overloaded && (
                  <span className="text-[11px] font-medium text-red-600">overloaded</span>
                )}
              </div>
            </div>
          )
        })}
        {(capacity.data ?? []).length === 0 && (
          <p className="text-xs text-slate-400">No active members.</p>
        )}
        <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!capacity.data?.length}>
          Save capacity
        </Button>
      </div>
    </Card>
  )
}

import { ScrollText, Search } from 'lucide-react'
import { useEffect, useState } from 'react'

import { useOrg } from '../components/OrgLayout'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  PageSpinner,
} from '../components/ui'
import { useAuditLogs } from '../lib/hooks'
import { isAdmin } from '../lib/types'
import { formatDateTime } from '../lib/utils'

const PAGE_SIZE = 50

export function AuditPage() {
  const { org, role, members } = useOrg()
  const [actionInput, setActionInput] = useState('')
  const [action, setAction] = useState('')
  const [offset, setOffset] = useState(0)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setAction(actionInput.trim())
      setOffset(0)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [actionInput])

  const logs = useAuditLogs(org.slug, action, offset, PAGE_SIZE)

  if (!isAdmin(role)) {
    return (
      <div className="p-6">
        <Card className="p-6 text-sm text-slate-600">
          Only admins and owners can view the audit trail.
        </Card>
      </div>
    )
  }

  const actorName = new Map(
    members.map((membership) => [
      membership.user_id,
      membership.user?.full_name || membership.user?.email || membership.user_id,
    ]),
  )
  const total = logs.data?.total ?? 0

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">Audit trail</h1>
        <p className="text-sm text-slate-500">
          Every security-relevant action inside {org.name}.
        </p>
      </div>

      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
        <Input
          className="pl-9"
          placeholder="Filter by action (e.g. task.updated)…"
          value={actionInput}
          onChange={(event) => setActionInput(event.target.value)}
        />
      </div>

      {logs.isLoading && <PageSpinner />}
      {logs.isError && (
        <ErrorState message="Could not load audit logs." onRetry={() => void logs.refetch()} />
      )}

      {logs.data?.items.length === 0 && (
        <EmptyState
          icon={<ScrollText className="h-8 w-8" />}
          title="No audit entries"
          description="Actions will show up here as your team works."
        />
      )}

      {logs.data && logs.data.items.length > 0 && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2.5 font-medium">When</th>
                  <th className="px-4 py-2.5 font-medium">Actor</th>
                  <th className="px-4 py-2.5 font-medium">Action</th>
                  <th className="px-4 py-2.5 font-medium">Target</th>
                  <th className="px-4 py-2.5 font-medium">IP</th>
                </tr>
              </thead>
              <tbody>
                {logs.data.items.map((log) => (
                  <tr key={log.id} className="border-t border-slate-100">
                    <td className="whitespace-nowrap px-4 py-2.5 text-slate-500">
                      {formatDateTime(log.created_at)}
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">
                      {log.actor_id ? (actorName.get(log.actor_id) ?? log.actor_id) : 'system'}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge className="bg-slate-100 font-mono text-slate-700">{log.action}</Badge>
                    </td>
                    <td className="px-4 py-2.5 text-slate-500">
                      {log.target_type ? `${log.target_type}:${log.target_id?.slice(0, 8) ?? '—'}` : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-slate-500">{log.ip ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 text-xs text-slate-500">
            <span>
              Showing {Math.min(offset + 1, total)}–{Math.min(offset + PAGE_SIZE, total)} of {total}
            </span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={offset === 0}
                onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset((value) => value + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}

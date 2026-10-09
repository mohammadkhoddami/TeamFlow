import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { useOrg } from '../components/OrgLayout'
import { Card, CardHeader, EmptyState, Field, Input, PageSpinner, Select } from '../components/ui'
import { worklogsApi } from '../lib/api'
import { useI18n } from '../lib/i18n'

function isoDate(offsetDays: number): string {
  const date = new Date()
  date.setDate(date.getDate() + offsetDays)
  return date.toISOString().slice(0, 10)
}

export function TimesheetPage() {
  const { org, members } = useOrg()
  const { t } = useI18n()
  const [from, setFrom] = useState(isoDate(-6))
  const [to, setTo] = useState(isoDate(0))
  const [userId, setUserId] = useState('')

  const timesheet = useQuery({
    queryKey: ['orgs', org.slug, 'timesheet', from, to, userId],
    queryFn: () =>
      worklogsApi.timesheet(org.slug, {
        date_from: `${from}T00:00:00Z`,
        date_to: `${to}T23:59:59Z`,
        user_id: userId || undefined,
      }),
  })

  const formatMinutes = (minutes: number) => {
    const hours = Math.floor(minutes / 60)
    const rest = minutes % 60
    if (hours > 0 && rest > 0) {
      return t('timesheet.durationHM', '{hours}h {minutes}m', { hours, minutes: rest })
    }
    if (hours > 0) return t('timesheet.durationH', '{hours}h', { hours })
    return t('timesheet.durationM', '{minutes}m', { minutes: rest })
  }

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">
          {t('timesheet.title', 'Timesheet')}
        </h1>
        <p className="text-sm text-slate-500">
          {t('timesheet.subtitle', 'Logged time by day, member and task.')}
        </p>
      </div>

      <Card className="flex flex-wrap items-end gap-3 p-4">
        <Field label={t('timesheet.from', 'From')}>
          <Input type="date" value={from} onChange={(event) => setFrom(event.target.value)} />
        </Field>
        <Field label={t('timesheet.to', 'To')}>
          <Input type="date" value={to} onChange={(event) => setTo(event.target.value)} />
        </Field>
        <Field label={t('timesheet.member', 'Member')}>
          <Select value={userId} onChange={(event) => setUserId(event.target.value)}>
            <option value="">{t('timesheet.everyone', 'Everyone')}</option>
            {members.map((membership) => (
              <option key={membership.user_id} value={membership.user_id}>
                {membership.user?.full_name || membership.user?.email || membership.user_id}
              </option>
            ))}
          </Select>
        </Field>
      </Card>

      {timesheet.isLoading && <PageSpinner />}
      {timesheet.data && (
        <>
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4">
            <Card className="px-4 py-3">
              <p className="text-[11px] uppercase tracking-wide text-slate-400">
                {t('timesheet.total', 'Total')}
              </p>
              <p className="text-xl font-semibold text-slate-800">
                {formatMinutes(timesheet.data.total_minutes)}
              </p>
            </Card>
            {timesheet.data.totals_by_user.slice(0, 7).map((total) => (
              <Card key={total.user_id ?? 'removed'} className="px-4 py-3">
                <p className="truncate text-[11px] uppercase tracking-wide text-slate-400">
                  {total.user_name}
                </p>
                <p className="text-xl font-semibold text-slate-800">
                  {formatMinutes(total.minutes)}
                </p>
              </Card>
            ))}
          </div>

          {timesheet.data.rows.length === 0 ? (
            <EmptyState
              title={t('timesheet.emptyTitle', 'No time logged')}
              description={t(
                'timesheet.emptyBody',
                "Log time from a task's Time tracking section.",
              )}
            />
          ) : (
            <Card className="overflow-hidden">
              <CardHeader title={t('timesheet.entries', 'Entries')} />
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-4 py-2.5 font-medium">{t('timesheet.day', 'Day')}</th>
                      <th className="px-4 py-2.5 font-medium">
                        {t('timesheet.member', 'Member')}
                      </th>
                      <th className="px-4 py-2.5 font-medium">{t('timesheet.task', 'Task')}</th>
                      <th className="px-4 py-2.5 font-medium">{t('timesheet.time', 'Time')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {timesheet.data.rows.map((row, index) => (
                      <tr key={`${row.task_id}-${row.day}-${index}`} className="border-t border-slate-100">
                        <td className="px-4 py-2.5 text-slate-500">{row.day}</td>
                        <td className="px-4 py-2.5 text-slate-600">{row.user_name}</td>
                        <td className="px-4 py-2.5">
                          {row.task_key && (
                            <span className="mr-1 font-mono text-[10px] text-slate-400">
                              {row.task_key}
                            </span>
                          )}
                          {row.task_title}
                        </td>
                        <td className="px-4 py-2.5 font-medium text-slate-700">
                          {formatMinutes(row.minutes)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  )
}

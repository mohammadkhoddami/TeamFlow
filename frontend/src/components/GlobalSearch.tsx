import { FolderKanban, MessageSquare, Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useGlobalSearch } from '../lib/hooks'
import { useI18n } from '../lib/i18n'
import { STATUS_LABELS } from '../lib/types'
import { cn } from '../lib/utils'
import { useOrg } from './OrgLayout'
import { Badge } from './ui'

export function GlobalSearch() {
  const { org } = useOrg()
  const { t } = useI18n()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement | null>(null)

  const results = useGlobalSearch(org.slug, query)
  const hasResults =
    (results.data?.tasks.length ?? 0) +
      (results.data?.comments.length ?? 0) +
      (results.data?.projects.length ?? 0) >
    0

  const openSearch = () => {
    setQuery('')
    setOpen(true)
    window.setTimeout(() => inputRef.current?.focus(), 0)
  }

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setQuery('')
        setOpen((value) => !value)
        window.setTimeout(() => inputRef.current?.focus(), 0)
      }
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const go = (path: string) => {
    setOpen(false)
    navigate(path)
  }

  return (
    <>
      <button
        type="button"
        onClick={openSearch}
        className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-500 transition-colors hover:border-slate-300 hover:text-slate-700"
        title={t('layout.searchTitle', 'Search (Ctrl+K)')}
      >
        <Search className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">{t('layout.search', 'Search')}</span>
        <kbd className="hidden rounded border border-slate-200 bg-white px-1 text-[10px] text-slate-400 md:inline">
          Ctrl K
        </kbd>
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/40 p-4 pt-[10vh]">
          <div
            className="w-full max-w-xl overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center gap-2 border-b border-slate-200 px-3 py-2.5">
              <Search className="h-4 w-4 shrink-0 text-slate-400" />
              <input
                ref={inputRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t(
                  'layout.searchPlaceholder',
                  'Search tasks, comments and projects…',
                )}
                className="min-w-0 flex-1 bg-transparent text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
              />
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                aria-label={t('layout.closeSearch', 'Close search')}
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="max-h-[60vh] overflow-y-auto p-2">
              {query.trim().length < 2 && (
                <p className="px-3 py-6 text-center text-xs text-slate-400">
                  {t(
                    'layout.searchHint',
                    'Type at least 2 characters. Full-text search covers titles, descriptions, comments and projects.',
                  )}
                </p>
              )}
              {results.isFetching && query.trim().length >= 2 && (
                <p className="px-3 py-4 text-center text-xs text-slate-400">
                  {t('layout.searching', 'Searching…')}
                </p>
              )}
              {!results.isFetching && query.trim().length >= 2 && !hasResults && (
                <p className="px-3 py-6 text-center text-xs text-slate-400">
                  {t('layout.noMatches', 'No matches for “{query}”.', { query: query.trim() })}
                </p>
              )}

              {(results.data?.tasks.length ?? 0) > 0 && (
                <section className="mb-1">
                  <p className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                    {t('layout.groupTasks', 'Tasks')}
                  </p>
                  {results.data!.tasks.map((hit) => (
                    <button
                      key={hit.id}
                      type="button"
                      onClick={() => go(`/org/${org.slug}/tasks?task=${hit.id}`)}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-slate-50"
                    >
                      {hit.key && (
                        <span className="shrink-0 font-mono text-[10px] text-brand-700">
                          {hit.key}
                        </span>
                      )}
                      <span className="min-w-0 flex-1 truncate text-sm text-slate-800">
                        {hit.title}
                      </span>
                      <Badge className="shrink-0 bg-slate-100 text-slate-600">
                        {t(`status.${hit.status}`, STATUS_LABELS[hit.status])}
                      </Badge>
                    </button>
                  ))}
                </section>
              )}

              {(results.data?.comments.length ?? 0) > 0 && (
                <section className="mb-1">
                  <p className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                    {t('layout.groupComments', 'Comments')}
                  </p>
                  {results.data!.comments.map((hit) => (
                    <button
                      key={hit.id}
                      type="button"
                      onClick={() => go(`/org/${org.slug}/tasks?task=${hit.task_id}`)}
                      className={cn(
                        'flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left hover:bg-slate-50',
                      )}
                    >
                      <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 text-slate-400" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium text-slate-600">
                          {hit.task_key ? `${hit.task_key} · ` : ''}
                          {hit.task_title}
                        </span>
                        <span className="block truncate text-xs text-slate-500">
                          {hit.snippet}
                        </span>
                      </span>
                    </button>
                  ))}
                </section>
              )}

              {(results.data?.projects.length ?? 0) > 0 && (
                <section>
                  <p className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                    {t('layout.groupProjects', 'Projects')}
                  </p>
                  {results.data!.projects.map((hit) => (
                    <button
                      key={hit.id}
                      type="button"
                      onClick={() => go(`/org/${org.slug}/projects/${hit.id}`)}
                      className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-slate-50"
                    >
                      <FolderKanban className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                      <span className="min-w-0 flex-1 truncate text-sm text-slate-800">
                        {hit.name}
                      </span>
                      {hit.key && (
                        <span className="shrink-0 font-mono text-[10px] text-slate-400">
                          {hit.key}
                        </span>
                      )}
                    </button>
                  ))}
                </section>
              )}
            </div>
          </div>
          <button
            type="button"
            aria-label={t('layout.closeSearchOverlay', 'Close search overlay')}
            className="absolute inset-0 -z-10 cursor-default"
            onClick={() => setOpen(false)}
          />
        </div>
      )}
    </>
  )
}

import { ChevronDown, ChevronRight, Network, Plus } from 'lucide-react'
import { useState } from 'react'

import { Avatar, Badge, Button, EmptyState } from '../ui'
import type { TaskRead, TaskTreeNode } from '../../lib/types'
import {
  PRIORITY_BADGE,
  PRIORITY_LABELS,
  STATUS_BADGE,
  STATUS_LABELS,
  TYPE_BADGE,
  TYPE_LABELS,
} from '../../lib/types'
import { cn } from '../../lib/utils'

export function TaskTree({
  nodes,
  onOpen,
  onAddChild,
}: {
  nodes: TaskTreeNode[]
  onOpen: (task: TaskRead) => void
  onAddChild?: (task: TaskRead) => void
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const toggle = (id: string) => {
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  if (nodes.length === 0) {
    return (
      <EmptyState
        icon={<Network className="h-8 w-8" />}
        title="No work items yet"
        description="Start with an epic, then break it down into stories and tasks."
      />
    )
  }

  const renderNode = (node: TaskTreeNode, depth: number): React.ReactNode => {
    const hasChildren = node.children.length > 0
    const isCollapsed = collapsed.has(node.id)
    const progress =
      node.child_count > 0 ? Math.round((node.done_child_count / node.child_count) * 100) : 0

    return (
      <div key={node.id}>
        <div
          role="button"
          tabIndex={0}
          onClick={() => onOpen(node)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') onOpen(node)
          }}
          className="group flex cursor-pointer items-center gap-2 border-b border-slate-100 px-3 py-2 pr-3 hover:bg-slate-50"
          style={{ paddingLeft: `${depth * 22 + 12}px` }}
        >
          {hasChildren ? (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                toggle(node.id)
              }}
              className="rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
              title={isCollapsed ? 'Expand' : 'Collapse'}
            >
              {isCollapsed ? (
                <ChevronRight className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </button>
          ) : (
            <span className="w-5" />
          )}

          <Badge className={TYPE_BADGE[node.type]}>{TYPE_LABELS[node.type]}</Badge>

          <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">
            {node.title}
          </span>

          {hasChildren && (
            <span className="hidden items-center gap-2 sm:flex">
              <span className="text-[11px] text-slate-400">
                {node.done_child_count}/{node.child_count}
              </span>
              <span className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
                <span
                  className={cn(
                    'block h-full rounded-full',
                    progress === 100 ? 'bg-emerald-500' : 'bg-brand-500',
                  )}
                  style={{ width: `${progress}%` }}
                />
              </span>
            </span>
          )}

          <Badge className={cn('hidden md:inline-flex', PRIORITY_BADGE[node.priority])}>
            {PRIORITY_LABELS[node.priority]}
          </Badge>

          {node.assignee ? (
            <Avatar
              name={node.assignee.full_name || node.assignee.email}
              email={node.assignee.email}
              size="sm"
            />
          ) : (
            <span className="hidden text-[11px] text-slate-400 md:inline">Unassigned</span>
          )}

          <Badge className={STATUS_BADGE[node.status]}>{STATUS_LABELS[node.status]}</Badge>

          {onAddChild && node.type !== 'task' && (
            <Button
              size="sm"
              variant="subtle"
              className="opacity-0 transition-opacity group-hover:opacity-100"
              onClick={(event) => {
                event.stopPropagation()
                onAddChild(node)
              }}
            >
              <Plus className="h-3.5 w-3.5" /> Child
            </Button>
          )}
        </div>
        {hasChildren && !isCollapsed && (
          <div>{node.children.map((child) => renderNode(child, depth + 1))}</div>
        )}
      </div>
    )
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      {nodes.map((node) => renderNode(node, 0))}
    </div>
  )
}

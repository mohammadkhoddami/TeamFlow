import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CornerDownRight, Send, SmilePlus, Trash2 } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'

import { useAuth } from '../../contexts/auth'
import { useToast } from '../../contexts/toast'
import { ApiError, commentsApi } from '../../lib/api'
import { qk } from '../../lib/hooks'
import type { CommentRead, ReactionSummary } from '../../lib/types'
import { REACTION_EMOJIS, canManage } from '../../lib/types'
import { cn, relativeTime } from '../../lib/utils'
import { useOrg } from '../OrgLayout'
import { Markdown } from '../Markdown'
import { MarkdownEditor } from '../MarkdownEditor'
import { Avatar, Button, Spinner } from '../ui'

function ReactionBar({
  comment,
  onToggle,
}: {
  comment: CommentRead
  onToggle: (emoji: string) => void
}) {
  const { user } = useAuth()
  const [pickerOpen, setPickerOpen] = useState(false)

  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1">
      {comment.reactions.map((reaction: ReactionSummary) => {
        const mine = Boolean(user && reaction.user_ids.includes(user.id))
        return (
          <button
            key={reaction.emoji}
            onClick={() => onToggle(reaction.emoji)}
            title={mine ? 'Remove reaction' : 'React'}
            className={cn(
              'flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-xs transition-colors',
              mine
                ? 'border-brand-200 bg-brand-50 text-brand-700'
                : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50',
            )}
          >
            <span>{reaction.emoji}</span>
            <span className="font-medium">{reaction.count}</span>
          </button>
        )
      })}
      <div className="relative">
        <button
          onClick={() => setPickerOpen((value) => !value)}
          title="Add reaction"
          className="rounded-full border border-transparent p-1 text-slate-400 hover:bg-white hover:text-slate-600"
        >
          <SmilePlus className="h-3.5 w-3.5" />
        </button>
        {pickerOpen && (
          <div className="absolute bottom-7 left-0 z-20 flex w-44 flex-wrap gap-1 rounded-lg border border-slate-200 bg-white p-2 shadow-lg">
            {REACTION_EMOJIS.map((emoji) => (
              <button
                key={emoji}
                onClick={() => {
                  onToggle(emoji)
                  setPickerOpen(false)
                }}
                className="rounded p-1 text-base hover:bg-slate-100"
              >
                {emoji}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export function CommentsSection({ taskId }: { taskId: string }) {
  const { user } = useAuth()
  const { role } = useOrg()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [body, setBody] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [replyTo, setReplyTo] = useState<CommentRead | null>(null)
  const [replyBody, setReplyBody] = useState('')
  const replyEditorRef = useRef<HTMLDivElement | null>(null)

  const comments = useQuery({
    queryKey: qk.comments(taskId),
    queryFn: () => commentsApi.list(taskId),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.comments(taskId) })
  }

  const create = useMutation({
    mutationFn: () => commentsApi.create(taskId, body.trim()),
    onSuccess: () => {
      setBody('')
      invalidate()
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not post comment'),
  })

  const reply = useMutation({
    mutationFn: (parent: CommentRead) =>
      commentsApi.create(taskId, replyBody.trim(), parent.id),
    onSuccess: () => {
      setReplyBody('')
      setReplyTo(null)
      invalidate()
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not post reply'),
  })

  const update = useMutation({
    mutationFn: (commentId: string) => commentsApi.update(commentId, draft.trim()),
    onSuccess: () => {
      setEditingId(null)
      invalidate()
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not update comment'),
  })

  const remove = useMutation({
    mutationFn: commentsApi.remove,
    onSuccess: invalidate,
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not delete comment'),
  })

  const toggleReaction = useMutation({
    mutationFn: async ({ comment, emoji }: { comment: CommentRead; emoji: string }) => {
      const mine = Boolean(
        user && comment.reactions.some((r) => r.emoji === emoji && r.user_ids.includes(user.id)),
      )
      if (mine) {
        await commentsApi.unreact(comment.id, emoji)
      } else {
        await commentsApi.react(comment.id, emoji)
      }
    },
    onSuccess: invalidate,
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not react'),
  })

  const { roots, repliesByRoot } = useMemo(() => {
    const all = comments.data ?? []
    const rootList = all.filter((entry) => !entry.root_id)
    const grouped = new Map<string, CommentRead[]>()
    for (const entry of all) {
      if (!entry.root_id) continue
      const list = grouped.get(entry.root_id) ?? []
      list.push(entry)
      grouped.set(entry.root_id, list)
    }
    return { roots: rootList, repliesByRoot: grouped }
  }, [comments.data])

  function canEdit(authorId: string | undefined): boolean {
    return authorId === user?.id || canManage(role)
  }

  function openReply(comment: CommentRead) {
    setReplyTo(comment)
    setReplyBody('')
    requestAnimationFrame(() =>
      replyEditorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }),
    )
  }

  function renderComment(comment: CommentRead, isReply: boolean) {
    return (
      <div
        key={comment.id}
        className={cn('flex items-start gap-2.5', isReply && 'ml-8 mt-2')}
      >
        <Avatar
          name={comment.author?.full_name || comment.author?.email || '?'}
          email={comment.author?.email}
          size="sm"
        />
        <div className="min-w-0 flex-1 rounded-lg bg-slate-50 px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-xs font-medium text-slate-700">
              {comment.author?.full_name || comment.author?.email || 'Deleted user'}
              <span className="ml-2 font-normal text-slate-400">
                {relativeTime(comment.created_at)}
              </span>
            </p>
            <div className="flex shrink-0 items-center gap-1">
              <button
                className="flex items-center gap-0.5 text-xs font-medium text-slate-500 hover:text-slate-700"
                onClick={() => openReply(comment)}
              >
                <CornerDownRight className="h-3 w-3" /> Reply
              </button>
              {canEdit(comment.author?.id) && editingId !== comment.id && (
                <>
                  <button
                    className="text-xs font-medium text-slate-500 hover:text-slate-700"
                    onClick={() => {
                      setEditingId(comment.id)
                      setDraft(comment.body)
                    }}
                  >
                    Edit
                  </button>
                  <button
                    className="rounded p-1 text-slate-400 hover:bg-white hover:text-red-600"
                    onClick={() => remove.mutate(comment.id)}
                    title="Delete comment"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </>
              )}
            </div>
          </div>

          {editingId === comment.id ? (
            <div className="mt-1.5 space-y-2">
              <MarkdownEditor
                className="bg-white"
                value={draft}
                onChange={setDraft}
                minRows={3}
                maxLength={20_000}
              />
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="secondary" onClick={() => setEditingId(null)}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={() => update.mutate(comment.id)}
                  disabled={draft.trim().length === 0}
                  loading={update.isPending}
                >
                  Save
                </Button>
              </div>
            </div>
          ) : (
            <Markdown text={comment.body} className="mt-0.5" emptyText="" />
          )}

          <ReactionBar
            comment={comment}
            onToggle={(emoji) => toggleReaction.mutate({ comment, emoji })}
          />

          {replyTo?.id === comment.id && (
            <div ref={replyEditorRef} className="mt-2 space-y-2 rounded-lg bg-white p-2">
              <MarkdownEditor
                value={replyBody}
                onChange={setReplyBody}
                minRows={2}
                maxLength={20_000}
                placeholder={`Reply to ${comment.author?.full_name || comment.author?.email || 'comment'}…`}
              />
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="secondary" onClick={() => setReplyTo(null)}>
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={() => reply.mutate(comment)}
                  disabled={replyBody.trim().length === 0}
                  loading={reply.isPending}
                >
                  <Send className="h-3.5 w-3.5" /> Reply
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-800">
        Comments{comments.data ? ` (${comments.data.length})` : ''}
      </h3>

      <div className="space-y-2">
        <MarkdownEditor
          value={body}
          onChange={setBody}
          minRows={3}
          maxLength={20_000}
          placeholder="Write a comment… (Markdown supported)"
        />
        <div className="flex justify-end">
          <Button
            size="sm"
            onClick={() => create.mutate()}
            disabled={body.trim().length === 0}
            loading={create.isPending}
          >
            <Send className="h-3.5 w-3.5" /> Comment
          </Button>
        </div>
      </div>

      <div className="space-y-3">
        {comments.isLoading && (
          <div className="flex justify-center py-3">
            <Spinner className="h-4 w-4 text-slate-400" />
          </div>
        )}
        {roots.map((root) => (
          <div key={root.id}>
            {renderComment(root, false)}
            {(repliesByRoot.get(root.id) ?? []).map((entry) => renderComment(entry, true))}
          </div>
        ))}
        {comments.data?.length === 0 && (
          <p className="text-xs text-slate-400">No comments yet.</p>
        )}
      </div>
    </section>
  )
}

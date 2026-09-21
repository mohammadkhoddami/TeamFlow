import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Send, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { useAuth } from '../../contexts/auth'
import { useToast } from '../../contexts/toast'
import { ApiError, commentsApi } from '../../lib/api'
import { qk } from '../../lib/hooks'
import { canManage } from '../../lib/types'
import { relativeTime } from '../../lib/utils'
import { useOrg } from '../OrgLayout'
import { Markdown } from '../Markdown'
import { MarkdownEditor } from '../MarkdownEditor'
import { Avatar, Button, Spinner } from '../ui'

export function CommentsSection({ taskId }: { taskId: string }) {
  const { user } = useAuth()
  const { role } = useOrg()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [body, setBody] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

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

  function canEdit(authorId: string | undefined): boolean {
    return authorId === user?.id || canManage(role)
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
        {comments.data?.map((comment) => (
          <div key={comment.id} className="flex items-start gap-2.5">
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
                {canEdit(comment.author?.id) && editingId !== comment.id && (
                  <div className="flex shrink-0 items-center gap-1">
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
                  </div>
                )}
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
            </div>
          </div>
        ))}
        {comments.data?.length === 0 && (
          <p className="text-xs text-slate-400">No comments yet.</p>
        )}
      </div>
    </section>
  )
}

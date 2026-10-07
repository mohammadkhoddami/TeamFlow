import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, ImagePlus, Paperclip, Trash2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'

import { useToast } from '../../contexts/toast'
import { ApiError, attachmentsApi, uploadToStorage } from '../../lib/api'
import { qk } from '../../lib/hooks'
import { formatBytes, relativeTime } from '../../lib/utils'
import { Badge, Button, Spinner } from '../ui'

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024

export function AttachmentsSection({
  taskId,
  onInsertMarkdown,
}: {
  taskId: string
  onInsertMarkdown?: (markdown: string) => void
}) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)

  const attachments = useQuery({
    queryKey: qk.attachments(taskId),
    queryFn: () => attachmentsApi.list(taskId),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.attachments(taskId) })
  }

  const remove = useMutation({
    mutationFn: attachmentsApi.remove,
    onSuccess: () => {
      toast.success('Attachment deleted')
      invalidate()
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : 'Could not delete file'),
  })

  async function handleFiles(files: FileList | null) {
    const file = files?.[0]
    if (!file) return
    if (file.size > MAX_UPLOAD_BYTES) {
      toast.error('Files are limited to 10 MB')
      return
    }
    setUploading(true)
    try {
      const contentType = file.type || 'application/octet-stream'
      const grant = await attachmentsApi.createUploadIntent(taskId, {
        filename: file.name,
        content_type: contentType,
        size: file.size,
      })
      await uploadToStorage(grant.upload_url, file, contentType)
      await attachmentsApi.confirm(taskId, grant.attachment.id)
      toast.success('File uploaded')
      invalidate()
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Upload failed')
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function download(attachmentId: string) {
    try {
      const grant = await attachmentsApi.downloadUrl(attachmentId)
      const link = document.createElement('a')
      link.href = grant.download_url
      link.target = '_blank'
      link.rel = 'noreferrer'
      document.body.appendChild(link)
      link.click()
      link.remove()
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Could not build download URL')
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800">
          Attachments{attachments.data ? ` (${attachments.data.length})` : ''}
        </h3>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => inputRef.current?.click()}
          loading={uploading}
        >
          <Upload className="h-3.5 w-3.5" /> Upload
        </Button>
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          onChange={(event) => void handleFiles(event.target.files)}
        />
      </div>

      {attachments.isLoading && (
        <div className="flex justify-center py-3">
          <Spinner className="h-4 w-4 text-slate-400" />
        </div>
      )}

      <ul className="space-y-1.5">
        {attachments.data?.map((attachment) => (
          <li
            key={attachment.id}
            className="flex items-center gap-2.5 rounded-lg border border-slate-200 px-3 py-2"
          >
            <Paperclip className="h-4 w-4 shrink-0 text-slate-400" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-slate-700">{attachment.filename}</p>
              <p className="text-[11px] text-slate-400">
                {formatBytes(attachment.size)} · {relativeTime(attachment.created_at)}
              </p>
            </div>
            {attachment.status !== 'uploaded' && (
              <Badge className="bg-amber-100 text-amber-700">{attachment.status}</Badge>
            )}
            {onInsertMarkdown && attachment.content_type.startsWith('image/') && (
              <button
                className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-brand-700"
                onClick={() =>
                  onInsertMarkdown(`![${attachment.filename}](attachment://${attachment.id})`)
                }
                title="Insert into description"
              >
                <ImagePlus className="h-4 w-4" />
              </button>
            )}
            <button
              className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              onClick={() => void download(attachment.id)}
              title="Download"
            >
              <Download className="h-4 w-4" />
            </button>
            <button
              className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
              onClick={() => remove.mutate(attachment.id)}
              title="Delete"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </li>
        ))}
      </ul>

      {attachments.data?.length === 0 && (
        <p className="text-xs text-slate-400">No files attached yet.</p>
      )}
    </section>
  )
}

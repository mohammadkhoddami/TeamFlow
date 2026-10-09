import type { LabelRead } from '../../lib/types'
import { useI18n } from '../../lib/i18n'
import { cn } from '../../lib/utils'

export function LabelPicker({
  labels,
  selectedIds,
  onChange,
}: {
  labels: LabelRead[]
  selectedIds: string[]
  onChange: (ids: string[]) => void
}) {
  const { t } = useI18n()
  if (labels.length === 0) {
    return (
      <p className="text-xs text-slate-500">
        {t(
          'labelPicker.empty',
          'No labels yet. Create them from the Labels page of this workspace.',
        )}
      </p>
    )
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {labels.map((label) => {
        const selected = selectedIds.includes(label.id)
        return (
          <button
            key={label.id}
            type="button"
            onClick={() =>
              onChange(
                selected
                  ? selectedIds.filter((id) => id !== label.id)
                  : [...selectedIds, label.id],
              )
            }
            className={cn(
              'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
              selected
                ? 'border-brand-300 bg-brand-50 text-brand-700'
                : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300',
            )}
          >
            <span
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: label.color ?? '#94a3b8' }}
            />
            {label.name}
          </button>
        )
      })}
    </div>
  )
}

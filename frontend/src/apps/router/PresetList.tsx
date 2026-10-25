// Built with Spec4 AI - https://spec4.ai
import type { RouterPreset } from '../../api/router'

/** Props for {@link PresetList}. */
export interface PresetListProps {
  presets: RouterPreset[]
  selectedId: string | null
  onSelect: (id: string) => void
  /** Disables every preset, e.g. while a run is in flight or runs are spent. */
  disabled?: boolean
}

/**
 * The six curated requests as a numbered, selectable list.
 *
 * Shows the request text only. The expected route and its reason are never
 * shown before a run: revealing them up front would tell the visitor what the
 * router is being measured against before they see what it decides.
 *
 * @param props - The presets, the current selection and the select handler.
 */
export function PresetList({ presets, selectedId, onSelect, disabled = false }: PresetListProps) {
  return (
    <ol className="grid gap-1.5" aria-label="Preset requests">
      {presets.map((preset, index) => {
        const selected = preset.id === selectedId
        return (
          <li key={preset.id}>
            <button
              type="button"
              aria-pressed={selected}
              disabled={disabled}
              onClick={() => onSelect(preset.id)}
              className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                selected
                  ? 'border-indigo-500 bg-indigo-50 dark:border-indigo-400 dark:bg-indigo-950'
                  : 'border-gray-200 bg-white hover:border-indigo-400 dark:border-gray-800 dark:bg-gray-900'
              }`}
            >
              {index + 1}. {preset.request}
            </button>
          </li>
        )
      })}
    </ol>
  )
}

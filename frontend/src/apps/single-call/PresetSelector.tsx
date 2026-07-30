// Built with Spec4 AI - https://spec4.ai
import type { PresetPrompt, SingleCallMode } from '../../api/singleCall'
import { schemaTitleOf } from './format'

interface PresetSelectorProps {
  presets: PresetPrompt[]
  /** The currently selected preset id, or null when the prompt is free text. */
  selectedId: string | null
  onSelect: (preset: PresetPrompt) => void
  mode: SingleCallMode
  /** The schema a free-text structured prompt would be held to. */
  defaultSchemaName: string
  disabled?: boolean
}

/**
 * The preset prompt chips, matching the mock's `.chip-row`.
 *
 * Each chip is labelled with its intent, which the capability's failure modes
 * require: "Preset prompts are labeled with their intent, such as summarize,
 * classify, or extract." The intent comes from the backend's curated set
 * rather than being re-derived from the label here, so the chip cannot drift
 * from what the preset actually does.
 *
 * Selecting a chip puts the preset's **full** prompt text into the textarea —
 * that is how the "show the full preset prompt text before submission"
 * mitigation is satisfied, and it is what the mock does. A second copy of the
 * text inside this component would only give the visitor two things to read.
 *
 * In Structured mode the chip also names the schema that preset targets, since
 * the mitigation asks for the preset's *mode* to be visible up front too, and
 * in structured mode the schema is the substantive half of what will be sent.
 */
export function PresetSelector({
  presets,
  selectedId,
  onSelect,
  mode,
  defaultSchemaName,
  disabled = false,
}: PresetSelectorProps) {
  const structured = mode === 'structured'

  return (
    <div>
      <span className="mb-1.5 block font-mono text-[11px] uppercase tracking-wide text-gray-500">
        Start from a preset
      </span>
      <div className="flex flex-wrap gap-1.5">
        {presets.map((preset) => {
          const selected = preset.id === selectedId
          const schemaName = schemaTitleOf(preset.response_schema)
          return (
            <button
              key={preset.id}
              type="button"
              disabled={disabled}
              aria-pressed={selected}
              onClick={() => onSelect(preset)}
              title={
                structured && schemaName
                  ? `${preset.intent} task — response must match ${schemaName}`
                  : `${preset.intent} task`
              }
              className={
                selected
                  ? 'rounded-full border border-violet-500 bg-violet-50 dark:bg-violet-950/40 px-2.5 py-1 text-[11px] text-violet-700 dark:text-violet-300 disabled:opacity-50'
                  : 'rounded-full border border-gray-200 dark:border-gray-800 px-2.5 py-1 text-[11px] text-gray-600 dark:text-gray-400 hover:border-violet-500 hover:text-gray-900 dark:hover:text-gray-100 disabled:opacity-50'
              }
            >
              <span className="font-medium">{preset.label}</span>
              <span className="ml-1.5 font-mono text-gray-400 dark:text-gray-500">
                {preset.intent}
              </span>
            </button>
          )
        })}
      </div>

      <p className="mt-2 text-[11px] leading-relaxed text-gray-500">
        {selectedId
          ? 'The full prompt is in the box below — exactly what will be sent. Editing it makes this your own prompt instead.'
          : structured
            ? `Your own prompt is held to the ${defaultSchemaName} schema; each preset brings its own.`
            : 'Or just write your own below.'}
      </p>
    </div>
  )
}


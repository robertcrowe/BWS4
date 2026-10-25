// Built with Spec4 AI - https://spec4.ai
import { MAX_REQUEST_CHARS } from '../../api/router'
import type { RouterPreset } from '../../api/router'
import { PresetList } from './PresetList'
import { RUN_CAP, SESSION_LIMIT_MESSAGE } from './runAllowance'

/** Props for {@link RunControls}. */
export interface RunControlsProps {
  presets: RouterPreset[]
  selectedId: string | null
  typed: string
  onSelect: (id: string) => void
  onType: (value: string) => void
  onRun: () => void
  pending: boolean
  /** True when this app's own 5-run limit is spent. */
  exhausted: boolean
  remaining: number
}

/**
 * The six presets, the free-text field, the run button and the counter.
 *
 * When the 5-run limit is spent the controls are **disabled in place** and a
 * message names that limit — this app's own, not the shared cap. Results
 * elsewhere on the page are untouched.
 */
export function RunControls({
  presets,
  selectedId,
  typed,
  onSelect,
  onType,
  onRun,
  pending,
  exhausted,
  remaining,
}: RunControlsProps) {
  const disabled = pending || exhausted
  const canRun = !disabled && (selectedId !== null || typed.trim().length > 0)

  return (
    <section
      aria-label="Request"
      className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900"
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-mono text-xs uppercase tracking-wide text-gray-500">Request</h2>
        <span
          data-testid="runs-remaining"
          className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-semibold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
        >
          Runs left {remaining} of {RUN_CAP}
        </span>
      </div>
      <PresetList
        presets={presets}
        selectedId={selectedId}
        onSelect={onSelect}
        disabled={disabled}
      />
      <label
        htmlFor="router-free-text"
        className="mt-3 block text-sm text-gray-600 dark:text-gray-400"
      >
        Or type your own (free-text runs earn no agreement credit):
      </label>
      <div className="mt-1 flex flex-wrap gap-2">
        <input
          id="router-free-text"
          type="text"
          value={typed}
          maxLength={MAX_REQUEST_CHARS}
          disabled={disabled}
          placeholder="e.g. How wide is the Hubble primary mirror?"
          onChange={(event) => onType(event.target.value)}
          className="min-w-[200px] flex-1 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-800 dark:bg-gray-950"
        />
        <button
          type="button"
          onClick={onRun}
          disabled={!canRun}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50 dark:bg-indigo-400 dark:text-gray-950"
        >
          Run
        </button>
      </div>
      <p className="mt-2 text-xs text-gray-500">
        Free text is screened by a moderation service before anything runs. Do not enter
        personal information.
      </p>
      {exhausted && (
        <p
          role="status"
          data-testid="session-limit"
          className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-300"
        >
          {SESSION_LIMIT_MESSAGE}
        </p>
      )}
    </section>
  )
}

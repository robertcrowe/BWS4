// Built with Spec4 AI - https://spec4.ai
import { useState } from 'react'

import type { PresetQuestion } from '../../api/orchestrated'

/**
 * The question form: preset chips, a free-form input, and the runs counter.
 *
 * The presets are prominent because the capability asks them to be — a
 * free-form question that fits no specialist well produces a forced pairing, so
 * offering sharper questions is a mitigation rather than decoration. They are
 * also pre-vetted server-side and skip the moderation gate, which on a
 * deployment with no moderation key is the difference between a run and a
 * refusal.
 *
 * **A preset id is dropped the moment the text is edited.** The server sends
 * the preset's *canonical* wording when an id is present, so an edited box
 * would display one question while the model received another — the same defect
 * the single-call app fixed.
 */

/** The longest question the API accepts, mirrored so the cap is visible. */
export const MAX_QUESTION_CHARS = 500

export interface QuestionFormProps {
  presets: PresetQuestion[]
  /** Runs left this hour. Zero disables the form. */
  remaining: number
  cap: number
  /** True while the coordinator is working. */
  busy: boolean
  /** Shown in place of the controls when this app's own limit is reached. */
  exhaustedMessage: string | null
  onSubmit: (question: string, presetId: string | null) => void
}

/**
 * Render the question form.
 *
 * @param props - Presets, allowance, busy state and the submit handler.
 * @returns The form panel.
 */
export function QuestionForm({
  presets,
  remaining,
  cap,
  busy,
  exhaustedMessage,
  onSubmit,
}: QuestionFormProps) {
  const [text, setText] = useState('')
  const [presetId, setPresetId] = useState<string | null>(null)
  const [invalid, setInvalid] = useState(false)

  const exhausted = exhaustedMessage !== null
  const disabled = busy || exhausted

  function choosePreset(preset: PresetQuestion) {
    setText(preset.text)
    setPresetId(preset.id)
    setInvalid(false)
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const question = text.trim()
    if (!question) {
      setInvalid(true)
      return
    }
    setInvalid(false)
    onSubmit(question, presetId)
  }

  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900">
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Ask a question</h3>

      <div className="mt-3 flex flex-wrap gap-2">
        {presets.map((preset) => (
          <button
            key={preset.id}
            type="button"
            disabled={disabled}
            onClick={() => choosePreset(preset)}
            className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs text-gray-700 transition-colors hover:border-violet-400 hover:text-violet-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-gray-800 dark:bg-gray-950 dark:text-gray-300 dark:hover:border-violet-500 dark:hover:text-violet-300"
          >
            {preset.text}
          </button>
        ))}
      </div>

      <form className="mt-4 flex flex-col gap-2 sm:flex-row" onSubmit={handleSubmit}>
        <label className="sr-only" htmlFor="orchestrated-question">
          Your question
        </label>
        <input
          id="orchestrated-question"
          type="text"
          value={text}
          maxLength={MAX_QUESTION_CHARS}
          disabled={disabled}
          placeholder="e.g. Should a small team self-host its own database?"
          onChange={(event) => {
            setText(event.target.value)
            // The server sends a preset's canonical text when an id is present.
            setPresetId(null)
          }}
          className="flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 disabled:cursor-not-allowed disabled:bg-gray-100 dark:border-gray-800 dark:bg-gray-950 dark:text-gray-100 dark:disabled:bg-gray-900"
        />
        <button
          type="submit"
          disabled={disabled}
          className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? 'Checking your question…' : 'Choose specialists'}
        </button>
      </form>

      <p className="mt-2 text-xs text-gray-500 dark:text-gray-500">
        {text.length} / {MAX_QUESTION_CHARS} characters. Please don&rsquo;t enter personal or
        confidential information — questions are sent to a third-party model provider.
      </p>

      {invalid ? (
        <p role="alert" className="mt-2 text-xs text-red-600 dark:text-red-400">
          Please enter a question or choose one of the curated presets above.
        </p>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-gray-100 pt-3 dark:border-gray-800">
        <span
          data-testid="runs-remaining"
          className="rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 font-mono text-xs text-gray-600 dark:border-gray-800 dark:bg-gray-950 dark:text-gray-400"
        >
          Runs remaining this hour: {remaining} / {cap}
        </span>
        <span className="text-xs text-gray-500 dark:text-gray-500">
          One coordinator call decides the pairing. Nothing is dispatched until you confirm.
        </span>
      </div>

      {exhausted ? (
        <p
          role="status"
          data-testid="session-limit-message"
          className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200"
        >
          {exhaustedMessage}
        </p>
      ) : null}

      <p className="mt-3 text-[11px] leading-relaxed text-gray-400 dark:text-gray-500">
        The runs counter is kept in this browser only — a per-device convenience, not a
        protection. The real limits are the server&rsquo;s hourly allowance and the fixed
        per-run call ceiling.
      </p>
    </section>
  )
}

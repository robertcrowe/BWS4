// Built with Spec4 AI - https://spec4.ai
import { MAX_QUESTION_CHARS } from '../../api/react'
import type { QuestionSuitability, ReactPreset } from '../../api/react'
import { SuitabilityHint } from './SuitabilityHint'

/**
 * `react_question_form`: pick a curated question, or type one, and start.
 *
 * **Pressing start begins the run immediately.** No plan is displayed first and
 * no approval is asked for mid-run — that is the precise contrast with the
 * Planning Agent example, and it is structurally true here rather than merely
 * described: there is no intermediate state between this control and the
 * stream, and no component in this app renders a plan.
 *
 * The free-form input carries the third-party disclosure the capability's
 * privacy section requires, and a client-side character cap matching the
 * server's. The advisory beside it is a **hint**: Start's enabled state does not
 * read the verdict at all, which is what makes "never a gate" a property of the
 * component tree rather than a promise in copy.
 *
 * When the advisory two-run allowance is spent, the controls are **disabled in
 * place** rather than unmounted, and the results region above is untouched. The
 * spec requires previous traces to stay on screen at exactly the moment a
 * clear-and-replace would wipe them.
 */

/** Props for {@link QuestionForm}. */
export interface QuestionFormProps {
  presets: ReactPreset[]
  selectedId: string | null
  typed: string
  onSelect: (id: string) => void
  onType: (value: string) => void
  onStart: () => void
  onStop: () => void
  pending: boolean
  /** True when this app's own two-run limit is spent. */
  exhausted: boolean
  remaining: number
  cap: number
  /** The server-fixed search budget, for the declared cost. */
  cycleBudget: number
  /** Shown when the controls are disabled, naming *which* limit was hit. */
  limitMessage: string | null
  /** The advisory verdict, or null for the neutral state. */
  suitability: QuestionSuitability | null
  /** True while the advisory is being fetched. */
  checking: boolean
  /** True once a check has been attempted for the current text. */
  checked: boolean
  /** Fired on blur, which is where the debounce lives. */
  onQuestionBlur: () => void
  /** A moderation refusal, which *is* an error rather than an advisory. */
  refusal: string | null
}

/**
 * Render the preset chips, the free-form input, and the start control.
 *
 * @param props - The selection, the handlers, and the allowance state.
 * @returns The question form.
 */
export function QuestionForm({
  presets,
  selectedId,
  typed,
  onSelect,
  onType,
  onStart,
  onStop,
  pending,
  exhausted,
  remaining,
  cap,
  cycleBudget,
  limitMessage,
  suitability,
  checking,
  checked,
  onQuestionBlur,
  refusal,
}: QuestionFormProps) {
  const tooLong = typed.length > MAX_QUESTION_CHARS
  const hasQuestion = selectedId !== null || (typed.trim().length > 0 && !tooLong)

  // **Start's enabled state does not mention the verdict.** Not an oversight —
  // the advisory must never become a precondition, so there is deliberately no
  // expression here it could be wired into.
  const disabled = pending || exhausted

  return (
    <section
      data-testid="react-question-form"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        Choose a multi-hop question
      </h3>

      <div
        className="mt-3 flex flex-wrap gap-2"
        data-testid="react-preset-chips"
        role="group"
        aria-label="Curated multi-hop questions"
      >
        {presets.map((preset) => {
          const active = preset.id === selectedId
          return (
            <button
              key={preset.id}
              type="button"
              aria-pressed={active}
              disabled={disabled}
              onClick={() => onSelect(preset.id)}
              title={preset.question}
              className={[
                'rounded-full border px-3 py-1.5 text-xs transition disabled:opacity-50',
                active
                  ? 'border-violet-500 bg-violet-50 text-violet-700 dark:bg-violet-950 dark:text-violet-300'
                  : 'border-gray-200 bg-white text-gray-600 hover:border-violet-500 dark:border-gray-800 dark:bg-gray-950 dark:text-gray-400',
              ].join(' ')}
            >
              {preset.label}
              <span className="ml-2 font-mono text-[10px] text-gray-500">
                {preset.hopCount} hops
                {preset.guaranteedFullyObserved ? ' · fully observed' : ''}
              </span>
            </button>
          )
        })}
      </div>

      {selectedId !== null && (
        <p
          className="mt-3 text-sm text-gray-700 dark:text-gray-300"
          data-testid="react-selected-question"
        >
          {presets.find((preset) => preset.id === selectedId)?.question}
        </p>
      )}

      <label
        htmlFor="react-question"
        className="mt-4 block text-xs font-medium text-gray-600 dark:text-gray-400"
      >
        Question (or write your own)
      </label>
      <input
        id="react-question"
        type="text"
        value={typed}
        disabled={disabled}
        onChange={(event) => onType(event.target.value)}
        onBlur={onQuestionBlur}
        maxLength={MAX_QUESTION_CHARS + 1}
        aria-describedby="react-question-disclosure"
        placeholder="e.g. Who directed the film that won Best Picture the year the ISS was first occupied?"
        className="mt-1.5 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 disabled:opacity-50 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
      />

      <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
        <p
          id="react-question-disclosure"
          data-testid="react-disclosure"
          className="text-[11px] text-gray-500 dark:text-gray-400"
        >
          Your question is sent to a third-party model provider and to a web
          search provider. Please don&apos;t enter personal or confidential
          information.
        </p>
        <span
          data-testid="react-char-count"
          className={`font-mono text-[10px] ${tooLong ? 'text-red-600 dark:text-red-400' : 'text-gray-500'}`}
        >
          {typed.length}/{MAX_QUESTION_CHARS}
        </span>
      </div>

      {tooLong && (
        <p
          data-testid="react-too-long"
          role="alert"
          className="mt-1.5 text-xs text-red-600 dark:text-red-400"
        >
          That question is longer than {MAX_QUESTION_CHARS} characters. Shorten
          it before starting a run.
        </p>
      )}

      {refusal !== null && (
        <p
          data-testid="react-moderation-refusal"
          role="alert"
          className="mt-3 rounded-lg border border-red-300 bg-red-50 p-3 text-xs text-red-800 dark:bg-red-950/40 dark:text-red-300"
        >
          {refusal}
        </p>
      )}

      {selectedId === null && (
        <SuitabilityHint
          verdict={suitability}
          checking={checking}
          attempted={checked}
        />
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onStart}
          disabled={disabled || !hasQuestion}
          className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {pending ? 'Running…' : 'Start run'}
        </button>

        {pending && (
          <button
            type="button"
            onClick={onStop}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-700 dark:border-gray-700 dark:text-gray-300"
          >
            Stop run
          </button>
        )}

        <span
          data-testid="react-runs-remaining"
          role="status"
          aria-label={`Runs remaining: ${remaining} of ${cap}`}
          className="rounded-full border border-gray-200 bg-white px-3 py-1 font-mono text-xs text-gray-600 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400"
        >
          {remaining} of {cap} runs remaining
        </span>

        <span className="font-mono text-xs text-gray-500 dark:text-gray-500">
          {`up to ${cycleBudget} searches + 1 answer call`}
        </span>
      </div>

      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
        No plan is shown before the run and you approve nothing mid-run — each
        next step follows an observation.
      </p>

      {/* Next to the control that spends it, not only in the overview above:
          this is the moment a visitor commits, and it is where the cost has to
          be legible. */}
      <div
        data-testid="react-quota-note"
        className="mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs leading-relaxed text-gray-600 dark:border-gray-800 dark:bg-gray-950 dark:text-gray-400"
      >
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          What a run costs.
        </strong>{' '}
        A run reserves a worst case of{' '}
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          {cycleBudget} search-cycle calls, 1 final-answer call and 1 post-run
          annotation call — 10 in all
        </strong>{' '}
        — and refunds whatever it does not spend, which is most of it whenever the
        loop answers early. Typing your own question adds{' '}
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          one suitability check
        </strong>
        ; the curated questions never spend one.
        <br />
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          You get {cap} runs
        </strong>{' '}
        — the gallery&apos;s tightest per-app limit, because this is the only
        example that can issue a search on every cycle, and so the most expensive
        one to run.
        <br />
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          ReAct agents in general run any number of cycles.
        </strong>{' '}
        Every limit on this page is this demonstration&apos;s choice about shared
        capacity, not a property of the pattern.
      </div>

      {limitMessage !== null && (
        <p
          data-testid="react-limit-message"
          role="alert"
          className="mt-3 rounded-lg border border-amber-400 bg-amber-50 p-3 text-xs text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
        >
          {limitMessage}
        </p>
      )}
    </section>
  )
}

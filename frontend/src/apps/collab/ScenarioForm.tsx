// Built with Spec4 AI - https://spec4.ai
import { SCENARIOS, WEIGHTINGS } from './choices'
import { DECLARED_BUDGET } from './runState'
import type { RunState } from './runState'

/**
 * `collab_scenario_form`: two closed choices, and no free text anywhere.
 *
 * **There is deliberately no text input on this screen, and none should be
 * added.** A scenario id from a fixed catalogue and a weighting id from a fixed
 * set are what make this the one example in the showcase that is injection-proof
 * by construction — nothing a visitor types reaches a prompt, because there is
 * nothing to type. That is also why there is no moderation affordance here:
 * adding one would imply free text exists somewhere, and it does not.
 *
 * The declared cost sits next to the start control rather than in the overview,
 * because "every run states its cost in model calls up front" is about the
 * moment of committing to spend, not about the page in general.
 */

/** Props for {@link ScenarioForm}. */
export interface ScenarioFormProps {
  scenarioId: string
  weightingId: string
  onScenarioChange: (id: string) => void
  onWeightingChange: (id: string) => void
  onStart: () => void
  pending: boolean
  state: RunState
}

/**
 * Render the scenario picker, the weighting picker, and the start control.
 *
 * @param props - The current selection, the handlers, and the run state.
 * @returns The scenario form.
 */
export function ScenarioForm({
  scenarioId,
  weightingId,
  onScenarioChange,
  onWeightingChange,
  onStart,
  pending,
  state,
}: ScenarioFormProps) {
  const capped = state.phase === 'cap_refused'
  const ready = scenarioId !== '' && weightingId !== ''
  const disabled = pending || capped || !ready

  return (
    <section
      data-testid="scenario-form"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        Choose a scenario and your priorities
      </h3>

      <label
        htmlFor="collab-scenario"
        className="mt-4 block text-xs font-medium text-gray-600 dark:text-gray-400"
      >
        Procurement scenario
      </label>
      <select
        id="collab-scenario"
        value={scenarioId}
        onChange={(event) => onScenarioChange(event.target.value)}
        className="mt-1.5 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
      >
        <option value="">Select a scenario…</option>
        {SCENARIOS.map((scenario) => (
          <option key={scenario.id} value={scenario.id}>
            {scenario.label}
          </option>
        ))}
      </select>
      {scenarioId !== '' && (
        <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
          {SCENARIOS.find((s) => s.id === scenarioId)?.detail}
        </p>
      )}

      <p className="mt-4 text-xs font-medium text-gray-600 dark:text-gray-400">
        Priority weighting
      </p>
      <div role="radiogroup" aria-label="Priority weighting" className="mt-1.5 flex flex-wrap gap-2">
        {WEIGHTINGS.map((weighting) => {
          const selected = weighting.id === weightingId
          return (
            <button
              key={weighting.id}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => onWeightingChange(weighting.id)}
              className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
                selected
                  ? 'border-violet-500 bg-violet-500/10 text-violet-700 dark:text-violet-300'
                  : 'border-gray-300 text-gray-600 hover:border-gray-400 dark:border-gray-700 dark:text-gray-400'
              }`}
            >
              {weighting.label}
            </button>
          )
        })}
      </div>
      {weightingId !== '' && (
        <p className="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
          {WEIGHTINGS.find((w) => w.id === weightingId)?.description}
        </p>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-gray-100 pt-4 dark:border-gray-800">
        <button
          type="button"
          data-testid="start-run"
          onClick={onStart}
          disabled={disabled}
          className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {pending ? 'Negotiating…' : 'Start negotiation'}
        </button>
        <span
          data-testid="declared-cost"
          className="font-mono text-xs text-gray-500 dark:text-gray-400"
        >
          This run costs {DECLARED_BUDGET.total} model calls ·{' '}
          {DECLARED_BUDGET.negotiation} negotiation + {DECLARED_BUDGET.explanation}{' '}
          post-award explanation
        </span>
      </div>

      <p className="mt-2 text-[11px] leading-relaxed text-gray-400 dark:text-gray-500">
        Runs are bounded by the framework&rsquo;s standard shared hourly and daily
        allowance, which every example app in this showcase draws on together. This app
        has no tightened per-app session counter of its own.
      </p>

      {capped && state.error && (
        <div
          data-testid="cap-refusal"
          className="mt-4 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4"
        >
          <p className="text-sm font-semibold text-amber-700 dark:text-amber-400">
            The shared allowance is exhausted
          </p>
          <p className="mt-1 text-sm leading-relaxed text-gray-700 dark:text-gray-300">
            {state.error.message} This is the{' '}
            <strong>showcase-wide limit shared by every example app</strong>, not a
            problem with the service — nothing was dispatched, because a round is
            refused up front rather than stalling halfway with a partial award.
          </p>
          {state.error.allowance && (
            <p className="mt-2 font-mono text-xs text-gray-600 dark:text-gray-400">
              {state.error.allowance.remaining} of {state.error.allowance.cap} calls
              left this hour · resets at {state.error.allowance.resetsAt.slice(11, 16)}{' '}
              UTC
            </p>
          )}
        </div>
      )}

      {state.phase === 'unreachable' && state.error && (
        <div
          data-testid="unreachable"
          className="mt-4 rounded-xl border border-red-500/40 bg-red-500/10 p-4"
        >
          <p className="text-sm font-semibold text-red-700 dark:text-red-400">
            The negotiation could not be started
          </p>
          <p className="mt-1 text-sm leading-relaxed text-gray-700 dark:text-gray-300">
            {state.error.message}
          </p>
        </div>
      )}
    </section>
  )
}

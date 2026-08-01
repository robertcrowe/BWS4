// Built with Spec4 AI - https://spec4.ai
import type { RunAllowance } from './runAllowance'
import { isExhausted, runsRemaining } from './runAllowance'
import { PRESET_GOALS } from './planState'

interface PlanGoalFormProps {
  city: string
  interests: string
  onCityChange: (value: string) => void
  onInterestsChange: (value: string) => void
  onSubmit: () => void
  planning: boolean
  /** Blocks the form while a run is streaming, so one visitor can't stack runs. */
  executing: boolean
  allowance: RunAllowance
  validationError: string | null
}

/**
 * plan_goal_form: city, interests, and the button that spends a planner call.
 *
 * Layout follows `.spec4/v4/design/mock.html`'s `#planForm` — preset chips, two
 * text inputs, submit with the runs-remaining tag beside it, inline validation
 * message underneath.
 *
 * The exhausted state is a teaching surface rather than a dead end: it says what
 * the limit is, why it exists, and when it lifts. The capability names visitor
 * confusion at this exact moment as a high-likelihood failure, and a disabled
 * button with no explanation is what causes it.
 */
export function PlanGoalForm({
  city,
  interests,
  onCityChange,
  onInterestsChange,
  onSubmit,
  planning,
  executing,
  allowance,
  validationError,
}: PlanGoalFormProps) {
  const exhausted = isExhausted(allowance)
  const remaining = runsRemaining(allowance)
  const busy = planning || executing
  const blocked = busy || exhausted

  return (
    <section className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
      <h3 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">
        Describe your trip day
      </h3>

      <div className="mb-4 flex flex-wrap gap-2">
        {PRESET_GOALS.map((preset) => (
          <button
            key={preset.city}
            type="button"
            disabled={blocked}
            onClick={() => {
              onCityChange(preset.city)
              onInterestsChange(preset.interests)
            }}
            className="rounded-full border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 px-3 py-1.5 text-left text-xs text-gray-600 hover:border-violet-500 disabled:opacity-50 dark:text-gray-400"
          >
            {preset.city} — {preset.interests}
          </button>
        ))}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          // Guarded as well as disabled: a form has more than one way to submit,
          // and a second planner call spends a unit of a shared hourly budget.
          if (!blocked) {
            onSubmit()
          }
        }}
      >
        <label
          htmlFor="planning-city"
          className="mb-1.5 block font-mono text-[11px] uppercase tracking-wide text-gray-500"
        >
          City
        </label>
        <input
          id="planning-city"
          type="text"
          value={city}
          onChange={(event) => onCityChange(event.target.value)}
          placeholder="e.g. Lisbon"
          disabled={blocked}
          className="mb-3 w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-violet-500 focus:outline-none disabled:opacity-60 dark:text-gray-100"
        />

        <label
          htmlFor="planning-interests"
          className="mb-1.5 block font-mono text-[11px] uppercase tracking-wide text-gray-500"
        >
          Interests
        </label>
        <input
          id="planning-interests"
          type="text"
          value={interests}
          onChange={(event) => onInterestsChange(event.target.value)}
          placeholder="e.g. street food, modern art, walkable neighborhoods"
          disabled={blocked}
          className="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-violet-500 focus:outline-none disabled:opacity-60 dark:text-gray-100"
        />

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <span
            className="rounded-full border border-gray-200 dark:border-gray-800 px-3 py-1 font-mono text-[11px] text-gray-500"
            data-testid="runs-remaining"
          >
            Runs remaining this hour: {remaining} / {allowance.cap}
          </span>
          <button
            type="submit"
            disabled={blocked}
            className="shrink-0 rounded-lg bg-violet-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
          >
            {planning ? 'Planning…' : 'Generate plan (1 planner call)'}
          </button>
        </div>
      </form>

      {validationError && (
        <p role="alert" className="mt-3 text-xs text-red-600 dark:text-red-400">
          {validationError}
        </p>
      )}

      {exhausted && (
        <p
          role="status"
          className="mt-3 rounded-lg border border-amber-200 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/30 px-3 py-2 text-xs leading-relaxed text-amber-800 dark:text-amber-300"
        >
          You&rsquo;ve used all {allowance.cap} planning runs for this hour. Planning agents are
          unbounded by nature — this demo caps them deliberately so one app can&rsquo;t drain the
          free-tier model and search budget the other examples share. The counter resets at the
          top of the hour.
        </p>
      )}
    </section>
  )
}

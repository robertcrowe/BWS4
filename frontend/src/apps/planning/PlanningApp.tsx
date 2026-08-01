// Built with Spec4 AI - https://spec4.ai
import { useEffect, useState } from 'react'

import type { Itinerary, PlanResponse } from '../../api/planning'
import { PlanningRequestError } from '../../api/planning'
import { usePlanMutation, useRetrySynthesis } from '../../api/usePlanning'
import { usePlanningRun } from '../../api/usePlanningRun'
import { PlanGoalForm } from './PlanGoalForm'
import { PlanReviewPanel } from './PlanReviewPanel'
import type { PanelPhase } from './planState'
import type { RunAllowance } from './runAllowance'
import { readAllowance, spendRun } from './runAllowance'

/**
 * The planning-agent example app: plan first, review, then execute.
 *
 * **The gate is the component structure, not a flag.** `run.start` is called
 * from exactly one place — the review panel's go-ahead button — and there is no
 * effect anywhere in this app that starts a run. That is what makes "no executor
 * call fires before the visitor's advance signal" a property of the code rather
 * than a promise, and it is what `planning.test.tsx` pins by asserting no run
 * request exists after a plan renders.
 *
 * **Plan and run state are separate on purpose.** The plan is a mutation result;
 * the run is a stream. Clearing the plan clears the run with it, so a second
 * submission can never leave the previous run's step results sitting under a new
 * plan — the same staleness trap the chained-calls app avoids by clearing its
 * result at the start of every submission.
 *
 * Layout follows `.spec4/v4/design/mock.html`'s `#screen-planning`: goal form,
 * then the review/execute panel.
 *
 * **The pattern explanation is not here.** It belongs to the screen, which
 * renders the shared `PatternSummary` from `example-apps.ts`, so the landing
 * directory and this screen describe the pattern in the same words. An in-app
 * card that explained it again shipped for one phase and was removed — the
 * single-call and chained-calls screens each shipped with exactly that
 * duplicate and had it removed too, which makes this the third time. If a card
 * here ever needs to say something, it must be something the summary does not.
 */
export function PlanningApp() {
  const planMutation = usePlanMutation()
  const retry = useRetrySynthesis()
  const run = usePlanningRun()

  const [city, setCity] = useState('')
  const [interests, setInterests] = useState('')
  const [plan, setPlan] = useState<PlanResponse | null>(null)
  /** The goal the current plan was built from, so execution sends the same one. */
  const [planned, setPlanned] = useState<{ city: string; interests: string } | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [allowance, setAllowance] = useState<RunAllowance>({ used: 0, cap: 3 })
  /** An itinerary composed by the retry path, which arrives outside the stream. */
  const [retryItinerary, setRetryItinerary] = useState<Itinerary | null>(null)

  // Read once on mount rather than during render: localStorage is not available
  // when this module is evaluated on the server or in a test that has not set
  // one up, and a render-time read would make the first paint depend on it.
  useEffect(() => setAllowance(readAllowance()), [])

  const itinerary = retryItinerary ?? run.itinerary
  const planning = planMutation.isPending
  const executing = run.status === 'streaming'

  const phase: PanelPhase = !plan
    ? 'empty'
    : executing
      ? 'executing'
      : itinerary
        ? 'complete'
        : run.runError || run.status === 'error'
          ? 'halted'
          : 'awaiting-goahead'

  function submit() {
    const trimmedCity = city.trim()
    const trimmedInterests = interests.trim()

    if (!trimmedCity || !trimmedInterests) {
      setValidationError('Please provide both a city and your interests before generating a plan.')
      return
    }

    setValidationError(null)
    // Clear the previous run before asking for a new plan: step results from an
    // earlier goal must never sit beneath a plan they were not produced for.
    setPlan(null)
    setRetryItinerary(null)
    run.reset()
    retry.reset()

    const goal = { city: trimmedCity, interests: trimmedInterests }
    planMutation.mutate(goal, {
      onSuccess: (response) => {
        setPlan(response)
        setPlanned(goal)
      },
    })
  }

  function execute() {
    if (!plan || !planned) {
      return
    }
    // The advance signal. A run is charged here rather than at planning time,
    // because the capability is explicit that a plan the visitor walks away from
    // costs them nothing.
    setAllowance(spendRun())
    run.start(planned, plan.plan)
  }

  function retrySynthesisOnly() {
    if (!plan || !planned) {
      return
    }
    // No allowance is spent: the visitor already paid for the research this
    // re-composes, and re-running the research is exactly what this avoids.
    retry.mutate(
      { goal: planned, plan: plan.plan, results: run.stepResults },
      { onSuccess: setRetryItinerary },
    )
  }

  return (
    <div className="space-y-4">
      <PlanGoalForm
        city={city}
        interests={interests}
        onCityChange={(value) => {
          setCity(value)
          if (validationError) {
            setValidationError(null)
          }
        }}
        onInterestsChange={(value) => {
          setInterests(value)
          if (validationError) {
            setValidationError(null)
          }
        }}
        onSubmit={submit}
        planning={planning}
        executing={executing}
        allowance={allowance}
        validationError={validationError}
      />

      {planMutation.isError && <PlanFailure error={planMutation.error} />}

      {plan && (
        <PlanReviewPanel
          plan={plan.plan}
          trimmedNote={plan.trimmed_note}
          phase={phase}
          results={run.stepResults}
          itinerary={itinerary}
          runError={run.runError}
          onExecute={execute}
          onRetrySynthesis={retrySynthesisOnly}
          retrying={retry.isPending}
          retryError={retry.error}
        />
      )}

      {run.status === 'error' && <StreamFailure error={run.error} />}
    </div>
  )
}

/**
 * The planner call failed, so there is no plan to review.
 *
 * A spent budget and an unreachable planner are separated because the remedies
 * differ: one resets at the top of the hour and cannot be retried into working.
 */
function PlanFailure({ error }: { error: unknown }) {
  const code = error instanceof PlanningRequestError ? error.code : 'request_failed'
  const message =
    error instanceof Error ? error.message : 'The plan could not be generated.'
  const budgetSpent = code === 'usage_limit_reached'

  return (
    <section
      role="alert"
      className="rounded-2xl border border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/30 p-4"
    >
      <p className="text-sm font-medium text-red-700 dark:text-red-300">
        {budgetSpent
          ? 'No plan was generated — this hour’s shared budget is spent.'
          : 'No plan was generated.'}
      </p>
      <p className="mt-1 text-xs text-red-700/90 dark:text-red-300/90">{message}</p>
      <p className="mt-1 font-mono text-[11px] text-red-600/80 dark:text-red-400/80">
        code: {code}
      </p>
    </section>
  )
}

/** The stream itself could not be opened or was cut mid-run. */
function StreamFailure({ error }: { error: unknown }) {
  const message =
    error instanceof Error ? error.message : 'The run stopped for an unknown reason.'

  return (
    <section
      role="alert"
      className="rounded-2xl border border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/30 p-4"
    >
      <p className="text-sm font-medium text-red-700 dark:text-red-300">
        The connection to the run was lost.
      </p>
      <p className="mt-1 text-xs text-red-700/90 dark:text-red-300/90">{message}</p>
    </section>
  )
}

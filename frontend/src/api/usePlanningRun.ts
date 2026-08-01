// Built with Spec4 AI - https://spec4.ai
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import type {
  Itinerary,
  Plan,
  PlanningEvent,
  PlanningGoal,
  PlanningRunError,
  StepResult,
} from './planning'
import { streamPlanningRun } from './planning'

/**
 * Where a run is. `complete` means the stream closed, not that every step
 * succeeded — a run can close having reported a failed step.
 */
export type PlanningRunStatus = 'idle' | 'streaming' | 'complete' | 'error'

export interface PlanningRunState {
  status: PlanningRunStatus
  /** Every event received so far, in arrival order. The single source of truth. */
  events: PlanningEvent[]
  plan: Plan | null
  stepResults: StepResult[]
  itinerary: Itinerary | null
  /** A transport failure: the stream could not be opened or was cut. */
  error: unknown
  /**
   * A failure the *run* reported and streamed, distinct from `error`.
   *
   * The run answered 200 and kept its results; this says what went wrong
   * alongside them. Collapsing the two would discard the partial output that
   * the capability's escalation path requires be shown.
   */
  runError: PlanningRunError | null
  start: (goal: PlanningGoal, plan: Plan) => void
  reset: () => void
}

/**
 * Narrow the event union by its name, so `.data` types correctly downstream.
 *
 * `events.find((e) => e.name === 'plan')?.data` would be typed as the union of
 * all three payloads — a plain predicate does not narrow through `find`.
 */
function isNamed<N extends PlanningEvent['name']>(name: N) {
  return (event: PlanningEvent): event is Extract<PlanningEvent, { name: N }> =>
    event.name === name
}

/**
 * Consume a planning run as it streams, accumulating typed state.
 *
 * Not a TanStack Query mutation, unlike every other quota-spending call in this
 * app. A mutation models one request producing one result; the value here
 * arrives in pieces over the life of the request, and the whole point of the
 * feature is that each piece is shown as it lands. Wrapping it in a mutation
 * would leave `data` undefined until the run finished — exactly the wait SSE
 * exists to remove.
 *
 * **The event log is the state; `plan`, `stepResults` and `itinerary` are
 * derived from it.** Keeping separate copies would let the rendered plan and
 * the rendered results disagree about what arrived, and this is an app whose
 * subject is showing honestly what the agent did.
 *
 * @returns The accumulated run state plus `start` and `reset`.
 */
export function usePlanningRun(): PlanningRunState {
  const [events, setEvents] = useState<PlanningEvent[]>([])
  const [status, setStatus] = useState<PlanningRunStatus>('idle')
  const [error, setError] = useState<unknown>(null)

  const controller = useRef<AbortController | null>(null)

  // Abort on unmount. A run left streaming into a component that no longer
  // exists is a stream the server is still doing work for.
  useEffect(() => () => controller.current?.abort(), [])

  const reset = useCallback(() => {
    controller.current?.abort()
    controller.current = null
    setEvents([])
    setStatus('idle')
    setError(null)
  }, [])

  const start = useCallback((goal: PlanningGoal, plan: Plan) => {
    // Abort any run already in flight before clearing its output, so a
    // superseded stream cannot append events to the new run's log.
    controller.current?.abort()
    const active = new AbortController()
    controller.current = active

    setEvents([])
    setError(null)
    setStatus('streaming')

    streamPlanningRun({
      goal,
      plan,
      signal: active.signal,
      onEvent: (event) => {
        if (!active.signal.aborted) {
          setEvents((previous) => [...previous, event])
        }
      },
    })
      .then(() => {
        if (!active.signal.aborted) {
          setStatus('complete')
        }
      })
      .catch((cause: unknown) => {
        // A deliberate abort is not a failure to report.
        if (active.signal.aborted) {
          return
        }
        setError(cause)
        setStatus('error')
      })
  }, [])

  const derived = useMemo(() => {
    const plan = events.find(isNamed('plan'))?.data ?? null
    const itinerary = events.find(isNamed('itinerary'))?.data ?? null
    const stepResults = events.filter(isNamed('step_result')).map((event) => event.data)
    const runError = events.find(isNamed('error'))?.data ?? null

    return { plan, stepResults, itinerary, runError }
  }, [events])

  return { status, events, error, start, reset, ...derived }
}

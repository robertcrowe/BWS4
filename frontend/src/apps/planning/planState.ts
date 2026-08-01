// Built with Spec4 AI - https://spec4.ai
/**
 * Deriving what the review panel shows from what the run has actually reported.
 *
 * Pure logic beside the components, testable without rendering and off React's
 * fast-refresh path — the arrangement `apps/chained-calls/chainState.ts` and
 * `apps/single-call/format.ts` established.
 *
 * **Everything here is derived from received events, never from a timer.** The
 * design mock animates step statuses with `setTimeout` against a fake backend;
 * doing that here would be inventing observations, which is the defect this
 * project has had to remove three times. A step is *running* only because every
 * earlier step has reported and this one has not — which is genuinely what the
 * stream tells us, since the backend executes strictly in order.
 */

import type { Itinerary, PlanStep, StepResult } from '../../api/planning'

/** Where the two-phase interaction currently is. */
export type PanelPhase =
  | 'empty'
  /** A plan is on screen and nothing has executed. */
  | 'awaiting-goahead'
  | 'executing'
  | 'complete'
  /** The run stopped early; whatever it produced is still shown. */
  | 'halted'

export type StepStatus = 'awaiting' | 'running' | 'completed' | 'failed'

/**
 * Work out each plan step's status from the results received so far.
 *
 * The synthesis step is the interesting case: it emits no `step_result` of its
 * own — its result *is* the itinerary — so it is judged by whether the itinerary
 * has arrived rather than by looking for a report that will never come.
 *
 * @param steps - The plan being executed.
 * @param results - Step results received so far, in arrival order.
 * @param phase - The panel's phase.
 * @param itinerary - The itinerary, once it has arrived.
 * @returns One status per plan step, in plan order.
 */
export function stepStatuses(
  steps: PlanStep[],
  results: StepResult[],
  phase: PanelPhase,
  itinerary: Itinerary | null,
): StepStatus[] {
  const byIndex = new Map(results.map((result) => [result.step_index, result]))
  const running = phase === 'executing'

  return steps.map((step, position) => {
    const reported = byIndex.get(step.index)
    if (reported) {
      return reported.status === 'failed' ? 'failed' : 'completed'
    }

    if (step.kind === 'synthesis') {
      if (itinerary) {
        return 'completed'
      }
      // Every research step has reported and the itinerary has not arrived, so
      // the synthesis call is the one in flight.
      const researchDone = steps
        .filter((candidate) => candidate.kind === 'research')
        .every((candidate) => byIndex.has(candidate.index))
      if (running && researchDone) {
        return 'running'
      }
      return phase === 'halted' ? 'failed' : 'awaiting'
    }

    // The backend runs steps strictly in order, so the first unreported step is
    // the one executing. Anything after it has genuinely not started.
    const earlierAllReported = steps
      .slice(0, position)
      .every((candidate) => byIndex.has(candidate.index))
    if (running && earlierAllReported) {
      return 'running'
    }
    return phase === 'halted' ? 'failed' : 'awaiting'
  })
}

/**
 * Describe where the itinerary is thinner than it should be.
 *
 * The backend has no `gap_notes` field, and inventing one would mean asserting
 * something no model produced. This reads the gaps off the evidence instead:
 * steps that failed, and blocks composed with no research behind them. An empty
 * `source_refs` is the model's own honest marker, not missing data.
 *
 * @param results - The run's step results.
 * @param itinerary - The composed itinerary, if any.
 * @returns Plain-language notes, empty when the run had no gaps.
 */
export function gapNotes(results: StepResult[], itinerary: Itinerary | null): string[] {
  const notes: string[] = []

  const failed = results.filter((result) => result.status === 'failed')
  if (failed.length > 0) {
    const numbers = failed.map((result) => result.step_index).join(', ')
    notes.push(
      `Research step${failed.length > 1 ? 's' : ''} ${numbers} did not complete, so the ` +
        'itinerary was composed without them rather than inventing detail to fill the gap.',
    )
  }

  const empty = results.filter(
    (result) => result.status === 'completed' && result.sources.length === 0,
  )
  if (empty.length > 0) {
    const numbers = empty.map((result) => result.step_index).join(', ')
    notes.push(
      `Step${empty.length > 1 ? 's' : ''} ${numbers} ran but found no usable results. ` +
        'That is a real outcome of the pattern, shown here rather than hidden.',
    )
  }

  const unsupported = (itinerary?.blocks ?? []).filter((block) => block.source_refs.length === 0)
  if (unsupported.length > 0) {
    const parts = unsupported.map((block) => block.time_of_day).join(', ')
    notes.push(
      `The ${parts} block${unsupported.length > 1 ? 's cite' : ' cites'} no research — ` +
        'a general suggestion rather than something this run found.',
    )
  }

  return notes
}

/** City and interests offered as one-click chips, taken from the design mock. */
export const PRESET_GOALS = [
  { city: 'Lisbon', interests: 'street food, modern art, walkable neighborhoods' },
  { city: 'Tokyo', interests: 'ramen, temples, quiet gardens' },
  { city: 'Mexico City', interests: 'museums, tacos, murals' },
]

// Built with Spec4 AI - https://spec4.ai
/**
 * The run's state, folded one envelope at a time.
 *
 * **Every envelope produces a new state, and nothing is buffered.** That is the
 * whole exhibit: an implementation that accumulated events and rendered once at
 * stream close would pass every assertion about the final screen and destroy
 * what the app is for — the loop's visible progression *is* the lesson. The
 * suite feeds envelopes one at a time and asserts the DOM grows between them,
 * which a buffered implementation cannot satisfy.
 *
 * A pure module beside the components, like `apps/collab/runState.ts` and
 * `apps/orchestrated/runState.ts`: testable without rendering, and off React's
 * fast-refresh path.
 *
 * **Cycles are keyed and appended, never rebuilt.** A cycle already on screen
 * is returned by reference when a later envelope does not touch it, so React
 * re-renders the cycle that changed rather than the whole trace — the same
 * device that keeps the collaboration app's two seller columns advancing
 * independently.
 */
import type {
  AnnotationResult,
  ExhaustionReason,
  GroundingAudit,
  ObservationSnippet,
  ObservationStatus,
  ReactRunEvent,
} from '../../api/react'

/** How far one cycle has got. Drives its badge and border in the trace. */
export type CyclePhase = 'thinking' | 'searching' | 'observed' | 'answered'

/** One cycle of the loop, as much of it as has arrived. */
export interface TraceCycle {
  cycle: number
  phase: CyclePhase
  thought: string
  /** `search` or `answer`, once the action envelope has arrived. */
  actionKind: 'search' | 'answer' | null
  /** The exact query issued, verbatim. Null until the action arrives. */
  query: string | null
  /** 1-based observation number, once the observation has arrived. */
  observationIndex: number | null
  results: ObservationSnippet[]
  observationStatus: ObservationStatus | null
  /** Why the search could not run, when it could not. */
  observationDetail: string | null
}

/** The run's terminal card. Exactly one, and never both. */
export type Terminal =
  | {
      kind: 'answer'
      answer: string
      observationCycles: number[]
      audit: GroundingAudit
      searchesUsed: number
      cycleBudget: number
    }
  | {
      kind: 'exhausted'
      reason: ExhaustionReason
      unresolved: string[]
      partialFindings: number[]
      searchesUsed: number
      cycleBudget: number
    }

/** Where the run is overall. */
export type RunPhase =
  | 'idle'
  | 'connecting'
  | 'running'
  | 'complete'
  | 'refused'
  | 'unreachable'

/** Everything the screen renders. */
export interface RunState {
  phase: RunPhase
  runId: string | null
  question: string
  /** Read from `run_started`, never hardcoded — the display mirrors the server. */
  cycleBudget: number
  searchesUsed: number
  cycles: TraceCycle[]
  terminal: Terminal | null
  /**
   * The post-run annotation, or null.
   *
   * **Null is the ordinary case, not an error.** Annotation is decorative and
   * arrives after the terminal card; a run that never emits it is complete and
   * correct, and the trace renders unlabelled with nothing to apologise for.
   */
  annotations: AnnotationResult | null
  error: { code: string; message: string } | null
}

/** A run that has not started. */
export function initialRunState(): RunState {
  return {
    phase: 'idle',
    runId: null,
    question: '',
    cycleBudget: 0,
    searchesUsed: 0,
    cycles: [],
    terminal: null,
    annotations: null,
    error: null,
  }
}

/**
 * Apply one envelope, returning the next state.
 *
 * Unrecognised events return the state unchanged rather than throwing, so the
 * backend can add an event type without breaking a deployed frontend.
 *
 * @param state - The state so far.
 * @param event - The envelope that just arrived.
 * @returns The next state. Cycles the event did not touch are returned by
 *   reference, so React can skip re-rendering them.
 */
export function applyRunEvent(state: RunState, event: ReactRunEvent): RunState {
  switch (event.kind) {
    case 'run_started':
      return {
        ...state,
        phase: 'running',
        runId: event.run_id,
        question: event.question,
        cycleBudget: event.cycle_budget,
      }

    case 'cycle_counter':
      return {
        ...state,
        searchesUsed: event.searches_used,
        cycleBudget: event.cycle_budget,
      }

    case 'cycle_thought':
      return {
        ...state,
        // Appended, not replaced: a thought opens a cycle, and the cycle that
        // decided to answer arrives after its predecessors are already drawn.
        cycles: [...state.cycles, blankCycle(event.cycle, event.thought)],
      }

    case 'cycle_action':
      return {
        ...state,
        cycles: patchCycle(state.cycles, event.cycle, (cycle) => ({
          ...cycle,
          phase: event.action_kind === 'answer' ? 'answered' : 'searching',
          actionKind: event.action_kind,
          query: event.query,
        })),
      }

    case 'cycle_observation':
      return {
        ...state,
        // The observation belongs to the newest cycle: the backend emits an
        // observation only for the search it just issued, and the envelope
        // carries the observation's own index rather than the cycle's.
        cycles: patchLast(state.cycles, (cycle) => ({
          ...cycle,
          phase: 'observed',
          observationIndex: event.index,
          results: event.results,
          observationStatus: event.status,
          observationDetail: event.detail,
        })),
      }

    case 'final_answer':
      return {
        ...state,
        phase: 'complete',
        runId: event.run_id,
        searchesUsed: event.searches_used,
        cycleBudget: event.cycle_budget,
        terminal: {
          kind: 'answer',
          answer: event.answer,
          observationCycles: event.observation_cycles,
          audit: event.audit,
          searchesUsed: event.searches_used,
          cycleBudget: event.cycle_budget,
        },
      }

    case 'budget_exhausted':
      return {
        ...state,
        phase: 'complete',
        runId: event.run_id,
        searchesUsed: event.searches_used,
        cycleBudget: event.cycle_budget,
        terminal: {
          kind: 'exhausted',
          reason: event.reason,
          unresolved: event.unresolved,
          partialFindings: event.partial_findings,
          searchesUsed: event.searches_used,
          cycleBudget: event.cycle_budget,
        },
      }

    case 'hop_annotations':
      return {
        ...state,
        annotations: {
          hops: event.hops,
          all_hops_observed: event.all_hops_observed,
          observed_count: event.observed_count,
          recalled_count: event.recalled_count,
          dropped: event.dropped,
          downgraded: event.downgraded,
        },
      }

    case 'error':
      return {
        ...state,
        phase: 'refused',
        error: { code: event.code, message: event.message },
      }

    default:
      return state
  }
}

function blankCycle(cycle: number, thought: string): TraceCycle {
  return {
    cycle,
    phase: 'thinking',
    thought,
    actionKind: null,
    query: null,
    observationIndex: null,
    results: [],
    observationStatus: null,
    observationDetail: null,
  }
}

function patchCycle(
  cycles: TraceCycle[],
  cycle: number,
  update: (current: TraceCycle) => TraceCycle,
): TraceCycle[] {
  return cycles.map((current) => (current.cycle === cycle ? update(current) : current))
}

function patchLast(
  cycles: TraceCycle[],
  update: (current: TraceCycle) => TraceCycle,
): TraceCycle[] {
  if (cycles.length === 0) {
    return cycles
  }
  return cycles.map((current, index) =>
    index === cycles.length - 1 ? update(current) : current,
  )
}

/**
 * The counter's label, e.g. `search 3 of 8`.
 *
 * Reads the budget the server sent rather than a constant, so the display
 * cannot claim a ceiling the run is not actually being held to.
 *
 * @param state - The run state.
 * @returns The label for the live counter.
 */
export function counterLabel(state: RunState): string {
  return `search ${state.searchesUsed} of ${state.cycleBudget || '—'}`
}

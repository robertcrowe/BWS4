// Built with Spec4 AI - https://spec4.ai
/**
 * Folds the dispatch stream into one column of state per specialist.
 *
 * A pure module beside the components, the arrangement `planState.ts` and
 * `plotTraces.ts` already use here: the fan-out's whole claim is that two
 * columns advance independently, and that claim is worth testing without
 * standing up a browser or a model.
 *
 * **State is derived from the events that arrived, never from a timer.** The
 * project has removed invented progress twice — the tool-use screen's fabricated
 * step animation and the chained-calls hand-off the mock animates — and this is
 * the surface where faking it would be easiest and least honest, since two
 * columns "both working" is exactly what a `setTimeout` could counterfeit. A
 * column is running because the server said it started, and it is done because
 * the server sent its answer.
 */
import type {
  Brief,
  DispatchEvent,
  MergedAnswerEvent,
  SpecialistAnswerEvent,
} from '../../api/orchestrated'

/** How one column is doing. */
export type ColumnPhase = 'waiting' | 'running' | 'ok' | 'failed' | 'timeout'

/** One specialist's column, as Phase 6 will bind it. */
export interface ColumnState {
  specialistId: string
  /** The brief this specialist was given. Heads the column. */
  instruction: string
  phase: ColumnPhase
  answer: string
  keyPoints: string[]
  /** Visitor-readable explanation, present only when the column has no answer. */
  error: string | null
}

/** Everything the dispatch stream has said so far. */
export interface DispatchState {
  columns: ColumnState[]
  /** Set once the fan-out settles with at least one column filled. */
  complete: boolean
  /** Specialists that produced an answer. */
  survivors: string[]
  /**
   * The run's final merged answer, once the fan-in lands.
   *
   * Null while the columns are still filling *and* during the merge itself, so
   * `complete && !merged` is exactly the "merging" state — derived from what
   * arrived rather than timed, like everything else here.
   */
  merged: MergedAnswerEvent | null
  /** A stream-level refusal, if one arrived. */
  error: { outcome: string; message: string; retryable: boolean; refundRun: boolean } | null
}

/**
 * Build the starting state: one waiting column per brief, in decision order.
 *
 * Columns exist before anything runs so the briefs are on screen from the
 * moment the visitor gives the go-ahead — the capability requires each column
 * to be headed by the brief its specialist received, which is what lets someone
 * see the two agents were given different instructions.
 *
 * @param briefs - The decision's briefs, in order.
 * @returns The initial state, with no events applied.
 */
export function initialDispatchState(briefs: Brief[]): DispatchState {
  return {
    columns: briefs.map((brief) => ({
      specialistId: brief.specialist_id,
      instruction: brief.instruction,
      phase: 'waiting',
      answer: '',
      keyPoints: [],
      error: null,
    })),
    complete: false,
    survivors: [],
    merged: null,
    error: null,
  }
}

function settle(column: ColumnState, data: SpecialistAnswerEvent): ColumnState {
  return {
    ...column,
    phase: data.status,
    answer: data.answer,
    keyPoints: data.key_points,
    error: data.error,
  }
}

/**
 * Apply one received event, returning new state.
 *
 * Only the column the event names changes; the other is returned by reference.
 * That is the mechanism behind "independently updating" — a slow specialist's
 * column cannot be reset or re-rendered by its partner settling.
 *
 * An event naming an unknown specialist is ignored rather than throwing: the
 * stream is remote input, and a column that does not exist has nothing to show.
 *
 * @param state - The state so far.
 * @param event - The received event.
 * @returns The new state.
 */
export function applyDispatchEvent(
  state: DispatchState,
  event: DispatchEvent,
): DispatchState {
  switch (event.name) {
    case 'specialist_status':
      return {
        ...state,
        columns: state.columns.map((column) =>
          column.specialistId === event.data.specialist_id
            ? { ...column, phase: 'running' }
            : column,
        ),
      }
    case 'specialist_answer':
      return {
        ...state,
        columns: state.columns.map((column) =>
          column.specialistId === event.data.specialist_id
            ? settle(column, event.data)
            : column,
        ),
      }
    case 'fan_out_complete':
      return { ...state, complete: true, survivors: event.data.survivors }
    case 'merged_answer':
      return { ...state, merged: event.data }
    case 'error':
      return {
        ...state,
        error: {
          outcome: event.data.outcome,
          message: event.data.message,
          retryable: event.data.retryable,
          refundRun: event.data.refund_run === true,
        },
      }
  }
}

/**
 * True while at least one column is running and none has settled.
 *
 * The state the demonstration turns on, and the reason it is derived rather
 * than stored: it is a fact about the columns, so it cannot drift away from
 * what they are showing.
 *
 * @param state - The state so far.
 * @returns Whether both columns are visibly in progress together.
 */
export function bothRunning(state: DispatchState): boolean {
  return state.columns.length > 0 && state.columns.every((c) => c.phase === 'running')
}

/**
 * True while the columns are done and the coordinator is still composing.
 *
 * Derived, not timed. The merge is one provider request with no intermediate
 * events, so this is the only honest way to say it is happening — the run has
 * finished fanning out and the final event has not arrived.
 *
 * @param state - The state so far.
 * @returns Whether the fan-in is in progress.
 */
export function merging(state: DispatchState): boolean {
  return state.complete && state.merged === null && state.error === null
}

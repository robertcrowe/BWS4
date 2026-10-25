// Built with Spec4 AI - https://spec4.ai
/**
 * A Router run's state, folded one event at a time.
 *
 * Every event produces a new state and nothing is buffered, so the stages, the
 * decision card and the ending appear as they happen. A pure module beside the
 * components, like `apps/react/runState.ts`: testable without rendering.
 */
import type {
  AnswerEvent,
  DecisionEvent,
  RouterRunEvent,
  RunEndEvent,
  StageEvent,
} from '../../api/router'

export type RunPhase = 'idle' | 'connecting' | 'running' | 'ended' | 'refused' | 'unreachable'

export interface RunError {
  code: string
  message: string
}

export interface RunState {
  phase: RunPhase
  runId: string | null
  request: string
  presetId: string | null
  /** Units the run holds, from `run_started`. */
  unitsReserved: number | null
  /** True for a comparison re-run. */
  isRerun: boolean
  originalRunId: string | null
  /** Stages reached so far, in order. The last is the current one. */
  stages: StageEvent[]
  decision: DecisionEvent | null
  answer: AnswerEvent | null
  end: RunEndEvent | null
  error: RunError | null
}

/** The state before any run. */
export function initialRunState(): RunState {
  return {
    phase: 'idle',
    runId: null,
    request: '',
    presetId: null,
    unitsReserved: null,
    isRerun: false,
    originalRunId: null,
    stages: [],
    decision: null,
    answer: null,
    end: null,
    error: null,
  }
}

/**
 * Apply one event.
 *
 * @param state - The current state.
 * @param event - The event that just arrived.
 * @returns The next state.
 */
export function applyRunEvent(state: RunState, event: RouterRunEvent): RunState {
  switch (event.kind) {
    case 'run_started':
      return {
        ...state,
        phase: 'running',
        runId: event.run_id,
        request: event.request,
        presetId: event.preset_id,
        unitsReserved: event.units_reserved,
        isRerun: event.is_rerun,
        originalRunId: event.original_run_id,
      }
    case 'stage':
      return { ...state, stages: [...state.stages, event] }
    case 'decision':
      return { ...state, decision: event }
    case 'answer':
      return { ...state, answer: event }
    case 'run_end':
      return { ...state, phase: 'ended', end: event }
  }
}

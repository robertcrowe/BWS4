// Built with Spec4 AI - https://spec4.ai
import { useCallback, useEffect, useRef, useState } from 'react'

import {
  dispatchSpecialists,
  startRun,
  type DelegationDecision,
  type RunError,
} from '../../api/orchestrated'
import {
  applyDispatchEvent,
  initialDispatchState,
  type DispatchState,
} from './runState'

/**
 * Drives one orchestrated run across its two streams.
 *
 * **Not a TanStack Query mutation**, unlike most quota-spending calls here and
 * for the same reason `usePlanningRun` is not: a mutation models one request
 * producing one result, and would leave `data` undefined until the run
 * finished. That is exactly the wait SSE exists to remove — the whole point of
 * this screen is that a column fills while the other is still working.
 *
 * **Two streams, and the gap between them is the pattern.** `submit()` runs the
 * coordinator and stops. `dispatch()` is a second request the visitor has to
 * ask for. There is no effect here that calls `dispatch()`, and there must
 * never be one: an auto-advance would make the confirmation gate decorative.
 *
 * `EventSource` is not an option for either — it is GET-only and both streams
 * start from a POST body.
 */

/** Where the run has got to. Drives which surfaces render. */
export type RunPhase =
  | 'idle'
  /** The question is with the moderation gate and the coordinator. */
  | 'checking'
  /** A decision is on screen, waiting for the visitor's go-ahead. */
  | 'decided'
  /** Both specialists are dispatched. */
  | 'running'
  /** The merged answer has arrived. */
  | 'complete'
  /** The run stopped and there is a message to show. */
  | 'failed'

export interface OrchestratedRun {
  phase: RunPhase
  question: string
  decision: DelegationDecision | null
  dispatch: DispatchState | null
  /** A refusal the server described, or a transport failure. */
  error: { outcome: string; message: string } | null
  /** Ask the coordinator to choose specialists. Spends one model call. */
  submit: (question: string, presetId: string | null) => Promise<void>
  /** The visitor's explicit go-ahead. Spends the rest of the run. */
  confirmDispatch: () => Promise<void>
  /** Clear everything back to idle, leaving stored prior runs alone. */
  reset: () => void
}

const TRANSPORT_FAILURE = 'transport_failure'

/**
 * Run the orchestrated pipeline and expose its state as it arrives.
 *
 * @param onComplete - Called once with the finished run, so the caller can
 *   record it against the advisory allowance. Called only when a merged answer
 *   actually arrived — a run that failed costs the visitor nothing.
 * @returns The run's live state and its two entry points.
 */
export function useOrchestratedRun(
  onComplete?: (question: string, decision: DelegationDecision, state: DispatchState) => void,
): OrchestratedRun {
  const [phase, setPhase] = useState<RunPhase>('idle')
  const [question, setQuestion] = useState('')
  const [decision, setDecision] = useState<DelegationDecision | null>(null)
  const [dispatch, setDispatch] = useState<DispatchState | null>(null)
  const [error, setError] = useState<{ outcome: string; message: string } | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      // An abandoned run keeps two specialists working against a stream nobody
      // is reading. Aborting lets the server see the disconnect and stop.
      abortRef.current?.abort()
    }
  }, [])

  const newController = useCallback(() => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    return controller
  }, [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setPhase('idle')
    setQuestion('')
    setDecision(null)
    setDispatch(null)
    setError(null)
  }, [])

  const submit = useCallback(
    async (text: string, presetId: string | null) => {
      const controller = newController()
      setPhase('checking')
      setQuestion(text)
      setDecision(null)
      setDispatch(null)
      setError(null)

      let refused: RunError | null = null
      try {
        await startRun({
          question: text,
          presetId,
          signal: controller.signal,
          onEvent: (event) => {
            if (!mountedRef.current) {
              return
            }
            if (event.name === 'delegation') {
              setDecision(event.data)
              setPhase('decided')
            } else {
              refused = event.data
            }
          },
        })
      } catch (cause) {
        if (controller.signal.aborted || !mountedRef.current) {
          return
        }
        setError({
          outcome: TRANSPORT_FAILURE,
          message: cause instanceof Error ? cause.message : 'The run could not be started.',
        })
        setPhase('failed')
        return
      }

      if (!mountedRef.current) {
        return
      }
      if (refused) {
        setError(refused)
        setPhase('failed')
      }
    },
    [newController],
  )

  const confirmDispatch = useCallback(async () => {
    if (!decision) {
      return
    }
    const controller = newController()
    // Columns exist before anything runs, each headed by its own brief, so the
    // visitor sees the two different instructions from the first frame.
    let state = initialDispatchState(decision.briefs)
    setDispatch(state)
    setPhase('running')
    setError(null)

    try {
      await dispatchSpecialists({
        decisionId: decision.decision_id,
        decision,
        question,
        signal: controller.signal,
        onEvent: (event) => {
          if (!mountedRef.current) {
            return
          }
          state = applyDispatchEvent(state, event)
          setDispatch(state)
        },
      })
    } catch (cause) {
      if (controller.signal.aborted || !mountedRef.current) {
        return
      }
      setError({
        outcome: TRANSPORT_FAILURE,
        message: cause instanceof Error ? cause.message : 'The run could not be completed.',
      })
      setPhase('failed')
      return
    }

    if (!mountedRef.current) {
      return
    }
    if (state.merged) {
      setPhase('complete')
      onComplete?.(question, decision, state)
      return
    }
    if (state.error) {
      setError({ outcome: state.error.outcome, message: state.error.message })
    }
    // Columns that arrived stay on screen either way; only the phase changes.
    setPhase('failed')
  }, [decision, newController, onComplete, question])

  return { phase, question, decision, dispatch, error, submit, confirmDispatch, reset }
}

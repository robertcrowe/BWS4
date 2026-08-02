// Built with Spec4 AI - https://spec4.ai
import { useCallback, useEffect, useRef, useState } from 'react'

import { CollabRequestError, startNegotiation } from '../../api/collab'
import type { RunEvent } from '../../api/collab'
import { loadRun, rehydrate, saveRun } from './runCache'
import { applyRunEvent, initialRunState } from './runState'
import type { RunState } from './runState'

/**
 * Drives one negotiation run and exposes the state the stream has built.
 *
 * Not a TanStack Query mutation, unlike most quota-spending calls in this
 * repo and for the same reason `usePlanningRun` and `useOrchestratedRun` are
 * not: a mutation models one request producing one result, and would leave
 * `data` undefined until the run finished — exactly the wait SSE exists to
 * remove. The event log is the state, and everything shown is derived from it,
 * so the stage rail and the columns cannot disagree about what arrived.
 *
 * Aborts on unmount and on a superseded run, so navigating away stops the
 * stream rather than leaving two sellers bidding into a page nobody is reading.
 *
 * On mount it rehydrates the visitor's last completed run from `localStorage`
 * with **no network call**. There is no server-side visitor identity here, so
 * without that a visitor who looked at another example and came back would find
 * six stages of waiting had produced nothing they could still see.
 */

/** What {@link useCollabRun} returns. */
export interface CollabRun {
  state: RunState
  /** True from the moment a run is requested until the stream closes. */
  pending: boolean
  start: (scenarioId: string, weightingId: string) => void
  reset: () => void
}

/**
 * Start and consume a negotiation run.
 *
 * @returns The run state, a pending flag, and the controls to start or clear.
 */
export function useCollabRun(): CollabRun {
  // Rehydrated lazily so the cache is read once, before first paint, rather
  // than in an effect that would flash an empty screen first.
  const [state, setState] = useState<RunState>(() => {
    const cached = loadRun()
    return cached ? rehydrate(cached, initialRunState()) : initialRunState()
  })
  const [pending, setPending] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const selection = useRef<{ scenarioId: string; weightingId: string } | null>(null)

  useEffect(() => {
    return () => {
      controller.current?.abort()
    }
  }, [])

  const start = useCallback((scenarioId: string, weightingId: string) => {
    // A superseded run is aborted rather than left running: it would keep
    // spending quota, and its events would interleave with the new run's.
    controller.current?.abort()
    const next = new AbortController()
    controller.current = next
    selection.current = { scenarioId, weightingId }

    // `connecting` rather than blank. Render's free tier spins down, so a cold
    // start of several seconds before the first event is a routine path.
    setState({ ...initialRunState(), phase: 'connecting' })
    setPending(true)

    void startNegotiation({
      scenarioId,
      weightingId,
      signal: next.signal,
      onEvent: (event: RunEvent) => {
        setState((current) => {
          const next = applyRunEvent(current, event)
          // Cached once, when the run finishes -- not per event. A
          // half-written run restored on a later visit would show an
          // interrupted negotiation with no way to tell it was interrupted.
          if (next.phase === 'complete' && selection.current) {
            saveRun(
              next,
              selection.current.scenarioId,
              selection.current.weightingId,
            )
          }
          return next
        })
      },
    })
      .catch((cause: unknown) => {
        if (next.signal.aborted) {
          return
        }
        // A transport failure is not a cap refusal, and the two must not read
        // the same: one the visitor waits out, the other they retry.
        setState((current) => ({
          ...current,
          phase: 'unreachable',
          error: {
            code: cause instanceof CollabRequestError ? cause.code : 'unreachable',
            message:
              cause instanceof Error
                ? cause.message
                : 'The negotiation stream could not be reached.',
            allowance: null,
          },
        }))
      })
      .finally(() => {
        if (!next.signal.aborted) {
          setPending(false)
        }
      })
  }, [])

  const reset = useCallback(() => {
    controller.current?.abort()
    setState(initialRunState())
    setPending(false)
  }, [])

  return { state, pending, start, reset }
}

// Built with Spec4 AI - https://spec4.ai
import { useCallback, useEffect, useRef, useState } from 'react'

import { ReactRequestError, startReactRun } from './react'
import type { ReactRunEvent } from './react'
import { applyRunEvent, initialRunState } from '../apps/react/runState'
import type { RunState } from '../apps/react/runState'

/**
 * Drives one ReAct run and exposes the state the stream has built so far.
 *
 * Not a TanStack Query mutation, unlike most quota-spending calls in this repo,
 * and for the same reason `usePlanningRun`, `useOrchestratedRun` and
 * `useCollabRun` are not: a mutation models one request producing one result and
 * would leave `data` undefined until the run finished — exactly the wait SSE
 * exists to remove.
 *
 * **Each envelope sets state as it arrives, and nothing is accumulated.** This
 * is the phase's named risk: a consumer that collected envelopes and set state
 * once at stream close would pass every assertion about the finished screen and
 * destroy the exhibit, because the loop's visible progression *is* the lesson.
 * `react-loop-run.test.tsx` delivers envelopes one at a time and asserts the DOM
 * grows between them, which a buffered implementation cannot satisfy.
 *
 * Aborts on unmount and on a superseded run, so navigating away stops the
 * stream rather than leaving a loop searching into a page nobody is reading.
 * That matters more here than anywhere else in the gallery: this is the most
 * expensive example per run, and the server refunds the reservation's unspent
 * remainder when the stream closes.
 */

/** What {@link useReactRun} returns. */
export interface ReactRun {
  state: RunState
  /** True from the moment a run is requested until the stream closes. */
  pending: boolean
  start: (options: { presetQuestionId?: string; visitorQuestion?: string }) => void
  /** Abort an in-flight run. Backs the visible stop control. */
  stop: () => void
  reset: () => void
}

/** Opaque per-tab identifier, correlating a visitor's runs in telemetry only. */
function sessionId(): string {
  return `react-${Math.random().toString(36).slice(2, 12)}`
}

/**
 * Start and consume a ReAct run, rendering each cycle as it arrives.
 *
 * @param onFinish - Called once when a run reaches a terminal card, with the
 *   run id and how it ended. Used to spend the advisory allowance, which is
 *   deliberately charged on *completion* so the counter and the stored record
 *   are written together.
 * @returns The run state, a pending flag, and the controls.
 */
export function useReactRun(
  onFinish?: (run: { runId: string; question: string; ending: 'answer' | 'exhausted' }) => void,
): ReactRun {
  const [state, setState] = useState<RunState>(initialRunState)
  const [pending, setPending] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const finished = useRef(false)

  useEffect(() => {
    return () => {
      controller.current?.abort()
    }
  }, [])

  const start = useCallback(
    (options: { presetQuestionId?: string; visitorQuestion?: string }) => {
      // A superseded run is aborted rather than left running: it would keep
      // spending quota, and its envelopes would interleave with the new run's.
      controller.current?.abort()
      const next = new AbortController()
      controller.current = next
      finished.current = false

      // `connecting` rather than blank: the first envelope can be a second or
      // two away, and an empty panel reads as nothing having happened.
      setState({ ...initialRunState(), phase: 'connecting' })
      setPending(true)

      void startReactRun({
        presetQuestionId: options.presetQuestionId,
        visitorQuestion: options.visitorQuestion,
        sessionId: sessionId(),
        signal: next.signal,
        onEvent: (event: ReactRunEvent) => {
          // One envelope, one state update. Nothing is queued.
          setState((current) => {
            const updated = applyRunEvent(current, event)
            if (
              !finished.current &&
              updated.terminal !== null &&
              updated.runId !== null &&
              onFinish
            ) {
              finished.current = true
              onFinish({
                runId: updated.runId,
                question: updated.question,
                ending: updated.terminal.kind === 'answer' ? 'answer' : 'exhausted',
              })
            }
            return updated
          })
        },
      })
        .catch((cause: unknown) => {
          if (next.signal.aborted) {
            return
          }
          // A transport failure is not a cap refusal, and the two must not read
          // the same: one the visitor retries, the other they wait out.
          setState((current) => ({
            ...current,
            phase: 'unreachable',
            error: {
              code: cause instanceof ReactRequestError ? cause.code : 'unreachable',
              message:
                cause instanceof Error
                  ? cause.message
                  : 'The run stream could not be reached.',
            },
          }))
        })
        .finally(() => {
          if (!next.signal.aborted) {
            setPending(false)
          }
        })
    },
    [onFinish],
  )

  const stop = useCallback(() => {
    controller.current?.abort()
    setPending(false)
  }, [])

  const reset = useCallback(() => {
    controller.current?.abort()
    setState(initialRunState())
    setPending(false)
  }, [])

  return { state, pending, start, stop, reset }
}

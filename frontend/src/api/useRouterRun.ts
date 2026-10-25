// Built with Spec4 AI - https://spec4.ai
import { useCallback, useEffect, useRef, useState } from 'react'

import { RouterRequestError, startRouterRerun, startRouterRun } from './router'
import type { RouterRunEvent } from './router'
import { applyRunEvent, initialRunState } from '../apps/router/runState'
import type { RunState } from '../apps/router/runState'

/**
 * Drives one Router run and exposes the state the stream has built so far.
 *
 * Not a TanStack Query mutation, for the same reason as `useReactRun`: a
 * mutation leaves `data` empty until the stream closes, which is exactly the
 * wait staged events exist to remove. No retries: a quota-spending call is
 * never re-sent automatically.
 *
 * Aborts on unmount and on a superseded run, so navigating away stops the
 * stream; the server then settles the unspent units.
 */

/** What {@link useRouterRun} returns. */
export interface RouterRun {
  state: RunState
  /** True from the moment a run is requested until the stream closes. */
  pending: boolean
  start: (options: RunOptions) => void
}

/**
 * What to start: a run of a request, or a comparison re-run of an earlier run.
 * A re-run carries the original run's id; the server decides if it is allowed.
 */
export type RunOptions =
  | { request: string; presetId?: string; rerunOf?: undefined }
  | { request: string; presetId: string; rerunOf: string }

/** Opaque per-tab visit id, correlating a visitor's runs in logs only. */
const VISIT_ID = `router-${Math.random().toString(36).slice(2, 12)}`

/**
 * Start and consume a Router run.
 *
 * @param onEnd - Called once when the run's `run_end` arrives, with the final
 *   state. This is where a run is spent — never earlier, so a refused run costs
 *   nothing.
 * @returns The run state, a pending flag, and `start`.
 */
export function useRouterRun(onEnd?: (state: RunState) => void): RouterRun {
  const [state, setState] = useState<RunState>(initialRunState)
  const [pending, setPending] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const ended = useRef(false)
  // The folded state, kept beside React's copy so the ending can be handed to
  // `onEnd` exactly as rendered, without waiting on a deferred updater.
  const current = useRef<RunState>(initialRunState())

  const commit = useCallback((next: RunState) => {
    current.current = next
    setState(next)
  }, [])

  useEffect(() => {
    return () => {
      controller.current?.abort()
    }
  }, [])

  const start = useCallback(
    (options: RunOptions) => {
      controller.current?.abort()
      const next = new AbortController()
      controller.current = next
      ended.current = false

      commit({
        ...initialRunState(),
        phase: 'connecting',
        request: options.request,
        presetId: options.presetId ?? null,
        isRerun: options.rerunOf !== undefined,
        originalRunId: options.rerunOf ?? null,
      })
      setPending(true)

      const onEvent = (event: RouterRunEvent) => {
        // One event, one state update. Nothing is queued.
        const updated = applyRunEvent(current.current, event)
        commit(updated)
        if (event.kind === 'run_end' && !ended.current) {
          ended.current = true
          onEnd?.(updated)
        }
      }
      const started =
        options.rerunOf !== undefined
          ? startRouterRerun({
              presetId: options.presetId,
              originalRunId: options.rerunOf,
              visitId: VISIT_ID,
              signal: next.signal,
              onEvent,
            })
          : startRouterRun({
              request: options.request,
              presetId: options.presetId,
              visitId: VISIT_ID,
              signal: next.signal,
              onEvent,
            })
      void started
        .catch((cause: unknown) => {
          if (next.signal.aborted) {
            return
          }
          const code = cause instanceof RouterRequestError ? cause.code : 'unreachable'
          commit({
            ...current.current,
            phase: code === 'unreachable' ? 'unreachable' : 'refused',
            error: {
              code,
              message: cause instanceof Error ? cause.message : 'The run could not be started.',
            },
          })
        })
        .finally(() => {
          if (!next.signal.aborted) {
            setPending(false)
          }
        })
    },
    [commit, onEnd],
  )

  return { state, pending, start }
}

// Built with Spec4 AI - https://spec4.ai
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'

import { ROUTER_HISTORY_KEY, useRouterHistory, useRouterPresets } from '../../api/router'
import type { RouteId } from '../../api/router'
import { useRouterRun } from '../../api/useRouterRun'
import { AgreementPanel } from './AgreementPanel'
import { KnowledgePanel } from './KnowledgePanel'
import { ResultCard } from './ResultCard'
import { RunControls } from './RunControls'
import { RunProgress } from './RunProgress'
import type { RunState } from './runState'
import { useRunAllowance } from './useRunAllowance'

/** Headings for a refusal, so the visitor can tell *which* limit or gate it was. */
const REFUSAL_HEADINGS: Record<string, string> = {
  shared_cap_reached: 'Shared framework cap',
  moderation_blocked: 'Request refused by the safety check',
  moderation_unavailable: 'Safety check unavailable',
  descriptions_not_ready: 'Router not ready',
}

/**
 * The Router app: what the router is told, the request, and every result.
 *
 * **A run is spent on its `run_end` event and on nothing else.** A refusal —
 * moderation, the shared cap — is an HTTP error before any run exists, so it
 * costs none of the five runs, and the message says which gate refused.
 *
 * **Exhaustion disables in place.** Earlier results stay on screen; only the
 * controls are disabled, with a message naming this app's own 5-run limit.
 */
export function RouterApp() {
  const presets = useRouterPresets()
  const history = useRouterHistory()
  const queryClient = useQueryClient()
  const allowance = useRunAllowance()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [typed, setTyped] = useState('')
  const { complete, completeRerun } = allowance

  const onEnd = useCallback(
    (state: RunState) => {
      if (state.isRerun && state.originalRunId && state.end) {
        completeRerun(state.originalRunId, { answer: state.answer, end: state.end })
      } else if (state.runId && state.decision && state.end) {
        complete({
          runId: state.runId,
          request: state.request,
          presetId: state.presetId,
          decision: state.decision,
          answer: state.answer,
          end: state.end,
        })
      }
      // The run may have written a history row: show it.
      void queryClient.invalidateQueries({ queryKey: ROUTER_HISTORY_KEY })
    },
    [complete, completeRerun, queryClient],
  )
  const run = useRouterRun(onEnd)

  if (presets.isPending) {
    return <p className="text-sm text-gray-500">Loading the router…</p>
  }

  if (presets.isError) {
    return (
      <p
        role="alert"
        className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
      >
        {presets.error.message}
      </p>
    )
  }

  const data = presets.data
  const labelFor = (id: RouteId) =>
    data.routeDescriptions.find((route) => route.id === id)?.label ?? id

  const startRun = () => {
    const preset = data.presets.find((candidate) => candidate.id === selectedId)
    if (preset) {
      run.start({ request: preset.request, presetId: preset.id })
    } else if (typed.trim()) {
      run.start({ request: typed.trim() })
    }
  }

  const live = run.state
  const inFlight = live.phase === 'connecting' || live.phase === 'running'
  const refusal = live.phase === 'refused' || live.phase === 'unreachable' ? live.error : null
  const results = [...allowance.results].reverse()

  return (
    <div className="grid gap-4">
      <KnowledgePanel
        block={data.routeDescriptionsBlock}
        sha256={data.routeDescriptionsSha256}
        routes={data.routeDescriptions}
        decisionMargin={data.decisionMargin}
        costOrder={data.costOrder}
      />

      <RunControls
        presets={data.presets}
        selectedId={selectedId}
        typed={typed}
        onSelect={(id) => {
          setSelectedId(id)
          setTyped('')
        }}
        onType={(value) => {
          setTyped(value)
          setSelectedId(null)
        }}
        onRun={startRun}
        pending={run.pending}
        exhausted={allowance.exhausted}
        remaining={allowance.remaining}
      />

      {refusal && (
        <div
          role="alert"
          data-testid="refusal"
          className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
        >
          <p className="font-semibold">
            {REFUSAL_HEADINGS[refusal.code] ?? 'The run could not be started'}
          </p>
          <p className="mt-1">{refusal.message}</p>
          <p className="mt-1 text-xs">No run was used.</p>
        </div>
      )}

      {inFlight && (
        <section
          aria-label="Current run"
          className="grid gap-3 rounded-xl border border-indigo-200 bg-white p-4 dark:border-indigo-900 dark:bg-gray-900"
        >
          <RunProgress stages={live.stages} active unitsReserved={live.unitsReserved} />
          {live.decision && (
            <ResultCard
              request={live.request}
              decision={live.decision}
              answer={live.answer}
              end={null}
              labelFor={labelFor}
              costOrder={data.costOrder}
            />
          )}
        </section>
      )}

      {results.length === 0 && !inFlight ? (
        <p className="rounded-xl border border-gray-200 bg-white p-4 text-center text-sm text-gray-500 dark:border-gray-800 dark:bg-gray-900">
          No run yet — choose a preset or type a request, then press Run.
        </p>
      ) : (
        <section aria-label="Results" className="grid gap-4">
          {results.map((result) => {
            const offer =
              result.end.rerun_eligible &&
              !result.rerun &&
              !allowance.exhausted &&
              result.presetId !== null
            const presetId = result.presetId
            return (
              <ResultCard
                key={result.runId}
                request={result.request}
                decision={result.decision}
                answer={result.answer}
                end={result.end}
                rerun={result.rerun}
                labelFor={labelFor}
                costOrder={data.costOrder}
                busy={run.pending}
                onRerun={
                  offer && presetId !== null
                    ? () =>
                        run.start({
                          request: result.request,
                          presetId,
                          rerunOf: result.runId,
                        })
                    : undefined
                }
              />
            )
          })}
        </section>
      )}

      <AgreementPanel
        history={history.data}
        presets={data.presets}
        error={history.isError ? history.error.message : null}
      />
    </div>
  )
}

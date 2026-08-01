// Built with Spec4 AI - https://spec4.ai
import { useCallback } from 'react'

import {
  OrchestratedRequestError,
  type DelegationDecision,
  type Specialist,
} from '../../api/orchestrated'
import { useRoster } from '../../api/useOrchestrated'
import { DelegationReview } from './DelegationReview'
import { MergedAnswerPanel } from './MergedAnswerPanel'
import { PatternOverview } from './PatternOverview'
import { QuestionForm } from './QuestionForm'
import { SpecialistColumns } from './SpecialistColumns'
import {
  SESSION_LIMIT_MESSAGE,
  SHOWCASE_LIMIT_MESSAGE,
  type StoredRun,
} from './runAllowance'
import type { DispatchState } from './runState'
import { SpecialistRoster } from './SpecialistRoster'
import { useOrchestratedRun } from './useOrchestratedRun'
import { useRunAllowance } from './useRunAllowance'

/**
 * The orchestrated-subagents example app.
 *
 * Composes the six surfaces the design names, in the order a visitor meets
 * them: what the pattern is, who is available, ask, review the delegation,
 * watch both specialists, read the merge.
 *
 * Three rules hold this together and none is cosmetic:
 *
 * 1. **Dispatch happens from one place only** — `DelegationReview`'s button.
 *    No effect here advances a decision into a run, because the confirmation
 *    gate is what makes the fan-out deliberate rather than automatic.
 * 2. **The two exhaustion messages never merge.** This app's own three-run
 *    counter and the showcase-wide hourly allowance are different limits with
 *    different owners and different remedies, and a visitor has to be able to
 *    tell which one stopped them.
 * 3. **Prior runs are re-rendered from storage**, so navigating away and back
 *    returns the answers alongside a counter that still agrees with them.
 */
export function OrchestratedApp() {
  const roster = useRoster()
  const allowance = useRunAllowance()
  const { complete } = allowance

  const onComplete = useCallback(
    (question: string, decision: DelegationDecision, state: DispatchState) => {
      complete({
        question,
        decision,
        columns: state.columns.map((column) => ({
          specialistId: column.specialistId,
          instruction: column.instruction,
          // A column that never left `waiting` or `running` when the stream
          // ended did not produce an answer, and is stored as what it was:
          // a specialist that failed to return one.
          status: column.phase === 'ok' || column.phase === 'timeout' ? column.phase : 'failed',
          answer: column.answer,
          keyPoints: column.keyPoints,
          error: column.error,
        })),
        merged: state.merged,
      })
    },
    [complete],
  )

  const run = useOrchestratedRun(onComplete)

  if (roster.isPending) {
    return (
      <p className="flex items-center gap-2.5 font-mono text-xs text-gray-500">
        <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gray-300 border-t-violet-500 dark:border-gray-700" />
        Loading the specialist roster…
      </p>
    )
  }

  if (roster.isError) {
    return <RosterFailure error={roster.error} />
  }

  const { specialists, presets } = roster.data
  // The showcase-wide refusal is the server's; this app's own limit is the
  // local counter's. They are sourced separately and worded separately.
  const showcaseExhausted = run.error?.outcome === 'usage_limit_reached'
  const sessionMessage = allowance.exhausted ? SESSION_LIMIT_MESSAGE : null

  return (
    <div className="space-y-4">
      <PatternOverview />

      <SpecialistRoster
        specialists={specialists}
        chosen={run.decision?.chosen_specialists ?? []}
      />

      <QuestionForm
        presets={presets}
        remaining={allowance.remaining}
        cap={allowance.allowance.cap}
        busy={run.phase === 'checking'}
        exhaustedMessage={sessionMessage}
        onSubmit={(question, presetId) => void run.submit(question, presetId)}
      />

      {run.phase === 'checking' ? (
        <p
          role="status"
          data-testid="checking-question"
          className="flex items-center gap-2.5 rounded-2xl border border-gray-200 bg-white p-4 font-mono text-xs text-gray-600 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400"
        >
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gray-300 border-t-violet-500 dark:border-gray-700" />
          Checking your question, then asking the coordinator to choose two specialists…
        </p>
      ) : null}

      {run.error ? (
        <RunRefusal
          outcome={run.error.outcome}
          message={showcaseExhausted ? SHOWCASE_LIMIT_MESSAGE : run.error.message}
        />
      ) : null}

      {run.decision ? (
        <DelegationReview
          decision={run.decision}
          specialists={specialists}
          dispatched={run.phase !== 'decided'}
          blockedMessage={sessionMessage}
          onDispatch={() => void run.confirmDispatch()}
        />
      ) : null}

      {run.dispatch ? (
        <SpecialistColumns columns={run.dispatch.columns} specialists={specialists} />
      ) : null}

      {run.dispatch?.merged ? (
        <MergedAnswerPanel merged={run.dispatch.merged} specialists={specialists} />
      ) : null}

      {run.dispatch && !run.dispatch.merged && run.phase === 'running' ? (
        <p
          role="status"
          data-testid="merging"
          className="flex items-center gap-2.5 rounded-2xl border border-gray-200 bg-white p-4 font-mono text-xs text-gray-600 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400"
        >
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gray-300 border-t-violet-500 dark:border-gray-700" />
          Waiting on the specialists, then the coordinator merges their answers…
        </p>
      ) : null}

      {allowance.runs.length > 0 ? (
        <PriorRuns runs={allowance.runs} specialists={specialists} />
      ) : null}
    </div>
  )
}

/**
 * A refusal the run reported, or a transport failure.
 *
 * **Rendered as plain text, never as markdown and never as HTML.** A refusal
 * message can quote what the visitor typed, so putting it through a renderer
 * would open a reflected-injection path into the page for no benefit at all.
 */
function RunRefusal({ outcome, message }: { outcome: string; message: string }) {
  return (
    <section
      role="alert"
      data-testid={`refusal-${outcome}`}
      className="rounded-2xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-900/60 dark:bg-amber-950/30"
    >
      <p className="font-mono text-xs text-amber-700 dark:text-amber-300">
        {outcome.replace(/_/g, ' ')}
      </p>
      <p
        data-testid="refusal-message"
        className="mt-1.5 text-sm leading-relaxed text-amber-900 dark:text-amber-100"
      >
        {message}
      </p>
      <p className="mt-1.5 text-xs text-amber-700/90 dark:text-amber-300/90">
        Nothing was dispatched, and this did not use one of your runs.
      </p>
    </section>
  )
}

/** Runs already completed this hour, re-rendered from local storage. */
function PriorRuns({
  runs,
  specialists,
}: {
  runs: StoredRun[]
  specialists: Specialist[]
}) {
  return (
    <section
      data-testid="prior-runs"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        Earlier runs this hour
      </h3>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-500">
        Kept in this browser so they survive navigating away and back. They roll over with
        the counter at the top of the hour.
      </p>
      <ul className="mt-3 space-y-3">
        {runs.map((run, index) => (
          <li
            key={`${run.question}-${index}`}
            className="rounded-xl border border-gray-200 bg-gray-50 p-3 dark:border-gray-800 dark:bg-gray-950"
          >
            <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
              {run.question}
            </p>
            <p className="mt-1 text-xs text-gray-500 dark:text-gray-500">
              {run.decision.chosen_specialists
                .map((id) => specialists.find((entry) => entry.id === id)?.displayName ?? id)
                .join(' + ')}
            </p>
            {run.merged ? (
              <p className="mt-2 text-xs leading-relaxed text-gray-600 dark:text-gray-400">
                {run.merged.text}
              </p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  )
}

/** The roster could not be fetched, so there is nothing to show. */
function RosterFailure({ error }: { error: unknown }) {
  const code = error instanceof OrchestratedRequestError ? error.code : 'request_failed'
  const message = error instanceof Error ? error.message : 'The roster could not be loaded.'

  return (
    <section
      role="alert"
      className="rounded-2xl border border-red-200 bg-red-50 p-4 dark:border-red-900/60 dark:bg-red-950/30"
    >
      <p className="text-sm font-medium text-red-700 dark:text-red-300">
        The specialist roster could not be loaded.
      </p>
      <p className="mt-1 text-xs text-red-700/90 dark:text-red-300/90">{message}</p>
      <p className="mt-1 font-mono text-[11px] text-red-600/80 dark:text-red-400/80">
        code: {code}
      </p>
    </section>
  )
}

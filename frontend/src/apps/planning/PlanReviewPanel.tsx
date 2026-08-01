// Built with Spec4 AI - https://spec4.ai
import type { Itinerary, Plan, PlanningRunError, StepResult } from '../../api/planning'
import type { PanelPhase, StepStatus } from './planState'
import { gapNotes, stepStatuses } from './planState'

interface PlanReviewPanelProps {
  plan: Plan
  trimmedNote: string | null
  phase: PanelPhase
  results: StepResult[]
  itinerary: Itinerary | null
  runError: PlanningRunError | null
  onExecute: () => void
  onRetrySynthesis: () => void
  retrying: boolean
  retryError: unknown
}

const STATUS_LABEL: Record<StepStatus, string> = {
  awaiting: 'awaiting go-ahead',
  running: 'running…',
  completed: 'complete',
  failed: 'failed',
}

const STATUS_BORDER: Record<StepStatus, string> = {
  awaiting: 'border-gray-200 dark:border-gray-800',
  running: 'border-violet-400 dark:border-violet-500',
  completed: 'border-emerald-400 dark:border-emerald-600',
  failed: 'border-red-300 dark:border-red-800',
}

/**
 * plan_review_execute_panel: the plan, the gate, and everything the run produces.
 *
 * Layout follows `.spec4/v4/design/mock.html`'s `#planResultPanel` — plan card
 * with an optional trim warning, the step list carrying each step's purpose and
 * status, the explicit go-ahead button, then step results appearing beneath it
 * and finally the itinerary.
 *
 * **The go-ahead is the only path to execution.** `onExecute` is wired to one
 * button's `onClick` and nothing else in this component starts a run — no
 * effect, no auto-advance, no timeout. That structure is what the gate test
 * pins.
 *
 * **Step statuses are derived from received results, never from a timer.** The
 * mock animates them with `setTimeout` against a fake backend; a real step's
 * duration is unknown until it reports, so a running indicator here means every
 * earlier step has reported and this one has not — which the strictly-ordered
 * backend makes a true statement rather than a guess.
 */
export function PlanReviewPanel({
  plan,
  trimmedNote,
  phase,
  results,
  itinerary,
  runError,
  onExecute,
  onRetrySynthesis,
  retrying,
  retryError,
}: PlanReviewPanelProps) {
  const statuses = stepStatuses(plan.steps, results, phase, itinerary)
  const executing = phase === 'executing'
  const notes = gapNotes(results, itinerary)
  const synthesisFailed = runError?.code === 'synthesis_failed'

  return (
    <section className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
      <h3 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">
        Proposed plan — review before anything runs
      </h3>

      {trimmedNote && (
        <p
          role="status"
          className="mb-3 rounded-lg border border-amber-200 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/30 px-3 py-2 text-xs leading-relaxed text-amber-800 dark:text-amber-300"
        >
          {trimmedNote}
        </p>
      )}

      <ol className="space-y-2" data-testid="plan-steps">
        {plan.steps.map((step, position) => {
          const status = statuses[position]
          return (
            <li
              key={step.index}
              className={`rounded-xl border ${STATUS_BORDER[status]} bg-gray-50 dark:bg-gray-950 p-3`}
            >
              <div className="flex items-start gap-3">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-violet-100 font-mono text-[11px] text-violet-700 dark:bg-violet-950 dark:text-violet-300">
                  {step.index}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {step.description}
                  </p>
                  {step.search_query && (
                    <p className="mt-1 font-mono text-[11px] text-gray-500">
                      searches: &ldquo;{step.search_query}&rdquo;
                    </p>
                  )}
                  <p className="mt-1.5 flex items-center gap-1.5 font-mono text-[11px] text-gray-500">
                    {status === 'running' && (
                      <span className="h-3 w-3 animate-spin rounded-full border-2 border-gray-300 dark:border-gray-700 border-t-violet-500" />
                    )}
                    {step.kind === 'research'
                      ? 'Executor step · shared search tool'
                      : 'Executor step · shared generation service'}{' '}
                    · Status: {STATUS_LABEL[status]}
                  </p>
                </div>
              </div>
            </li>
          )
        })}
      </ol>

      {phase === 'awaiting-goahead' && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={onExecute}
            className="rounded-lg bg-violet-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-violet-500"
          >
            Execute plan ({plan.steps.length} steps)
          </button>
          <span className="font-mono text-[11px] text-gray-500">
            Nothing executes until you give this explicit go-ahead.
          </span>
        </div>
      )}

      {executing && results.length === 0 && (
        <p className="mt-4 flex items-center gap-2.5 font-mono text-xs text-gray-500">
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gray-300 dark:border-gray-700 border-t-violet-500" />
          Executor step 1 running — results appear here as each step completes.
        </p>
      )}

      {results.length > 0 && (
        <div className="mt-5 space-y-3" data-testid="step-results">
          <h4 className="font-mono text-[11px] uppercase tracking-wide text-gray-500">
            Step results
          </h4>
          {results.map((result) => (
            <StepResultCard key={result.step_index} result={result} />
          ))}
        </div>
      )}

      {runError && !synthesisFailed && <RunNotice error={runError} />}

      {synthesisFailed && (
        <div className="mt-4 rounded-xl border border-amber-200 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/30 p-4">
          <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
            {runError.message}
          </p>
          <p className="mt-1 text-xs text-amber-700/90 dark:text-amber-400/90">
            The research above is preserved. Retrying re-runs only the final step, so nothing is
            searched again — and it does not cost another run.
          </p>
          <button
            type="button"
            onClick={onRetrySynthesis}
            disabled={retrying}
            className="mt-3 rounded-md border border-amber-300 dark:border-amber-800 px-2.5 py-1 text-xs text-amber-800 hover:bg-amber-100 disabled:opacity-50 dark:text-amber-300 dark:hover:bg-amber-900/40"
          >
            {retrying ? 'Composing…' : 'Retry synthesis only'}
          </button>
          {retryError !== null && retryError !== undefined && (
            <p className="mt-2 text-xs text-red-600 dark:text-red-400">
              {retryError instanceof Error ? retryError.message : 'The retry failed.'}
            </p>
          )}
        </div>
      )}

      {itinerary && (
        <div className="mt-5" data-testid="itinerary">
          <h4 className="mb-2 font-mono text-[11px] uppercase tracking-wide text-gray-500">
            Final output · One-day itinerary for {itinerary.city}
          </h4>

          {notes.length > 0 && (
            <ul
              className="mb-3 space-y-1 rounded-lg border border-amber-200 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/30 px-3 py-2"
              data-testid="gap-notes"
            >
              {notes.map((note) => (
                <li key={note} className="text-xs leading-relaxed text-amber-800 dark:text-amber-300">
                  {note}
                </li>
              ))}
            </ul>
          )}

          <div className="space-y-3">
            {itinerary.blocks.map((block) => (
              <div
                key={block.time_of_day}
                className="rounded-xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 p-3"
              >
                <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                  <strong className="text-sm capitalize text-gray-900 dark:text-gray-100">
                    {block.time_of_day}
                  </strong>
                  <span className="font-mono text-[11px] text-gray-500">
                    {block.source_refs.length > 0
                      ? `from step ${block.source_refs.join(', ')} research`
                      : 'no research behind this block'}
                  </span>
                </div>
                <p className="text-sm text-gray-700 dark:text-gray-300">{block.activity}</p>
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  Why it matches: {block.why_it_matches}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

/** One completed or failed step, shown honestly either way. */
function StepResultCard({ result }: { result: StepResult }) {
  const failed = result.status === 'failed'

  return (
    <div
      className={`rounded-xl border ${
        failed
          ? 'border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/20'
          : 'border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950'
      } p-3`}
    >
      <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
        <strong className="text-sm text-gray-900 dark:text-gray-100">
          Step {result.step_index} result
        </strong>
        <span
          className={`rounded-full px-2 py-0.5 font-mono text-[11px] ${
            failed
              ? 'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300'
              : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300'
          }`}
        >
          {failed ? 'failed' : `${result.sources.length} source(s)`}
        </span>
      </div>
      <p className="text-sm text-gray-700 dark:text-gray-300">{result.summary}</p>
      {result.sources.length > 0 && (
        <ul className="mt-2 space-y-1">
          {result.sources.map((source) => (
            <li key={source.url} className="truncate text-xs">
              <a
                href={source.url}
                target="_blank"
                rel="noopener noreferrer nofollow"
                className="text-violet-600 hover:underline dark:text-violet-400"
              >
                {source.title}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * A run that stopped for a reason other than a failed synthesis.
 *
 * Quota exhaustion is separated from the rest because the remedy differs: it
 * resets at the top of the hour and retrying cannot make it work, so the copy says to come
 * back rather than to try again.
 */
function RunNotice({ error }: { error: PlanningRunError }) {
  const quota = error.code === 'usage_limit_reached' || error.code === 'call_ceiling_reached'

  return (
    <div
      role="alert"
      className="mt-4 rounded-xl border border-amber-200 dark:border-amber-900/60 bg-amber-50 dark:bg-amber-950/30 p-4"
    >
      <p className="text-sm font-medium text-amber-800 dark:text-amber-300">{error.message}</p>
      <p className="mt-1 text-xs text-amber-700/90 dark:text-amber-400/90">
        {quota
          ? 'Everything completed above is preserved — an agent run never silently discards work it has already paid for. The shared budget resets at the top of the hour.'
          : 'Whatever completed above is preserved and shown as-is.'}
      </p>
      <p className="mt-1 font-mono text-[11px] text-amber-700/70 dark:text-amber-400/70">
        code: {error.code}
      </p>
    </div>
  )
}

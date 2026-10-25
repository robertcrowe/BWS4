// Built with Spec4 AI - https://spec4.ai
import type { AnswerEvent, DecisionEvent, RouteId, RunEndEvent } from '../../api/router'
import type { StoredRerun } from './runAllowance'
import { AnswerPanel } from './AnswerPanel'
import { CostStripView } from './CostStripView'
import { DecisionCard } from './DecisionCard'

/** Props for {@link ResultCard}. */
export interface ResultCardProps {
  request: string
  decision: DecisionEvent
  answer: AnswerEvent | null
  end: RunEndEvent | null
  labelFor: (route: RouteId) => string
  costOrder: RouteId[]
  /** The comparison re-run, once made. */
  rerun?: StoredRerun | null
  /** Shown only when the re-run may be offered; omitted otherwise. */
  onRerun?: () => void
  /** True while another run is in flight, so the offer is disabled. */
  busy?: boolean
}

/**
 * One run: the request, the decision card, the dispatched route's answer
 * labelled with its path, and — once the run has ended — the unit accounting.
 */
export function ResultCard({
  request,
  decision,
  answer,
  end,
  labelFor,
  costOrder,
  rerun = null,
  onRerun,
  busy = false,
}: ResultCardProps) {
  return (
    <article
      aria-label={`Result for: ${request}`}
      className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900"
    >
      <p className="mb-3 text-sm text-gray-600 dark:text-gray-400">
        <span className="font-semibold">Request:</span> {request}
      </p>
      <DecisionCard decision={decision} labelFor={labelFor} costOrder={costOrder} />
      {rerun ? (
        <div className="mt-3">
          <h4 className="mb-2 font-mono text-xs uppercase tracking-wide text-gray-500">
            Side by side
          </h4>
          <div className="grid gap-3 md:grid-cols-2" data-testid="side-by-side">
            <div className="min-w-0 rounded-lg border border-gray-200 p-3 dark:border-gray-800">
              <p className="mb-2 text-xs font-semibold">
                Original · {end ? labelFor(end.dispatched_route) : ''}
              </p>
              {answer && <AnswerPanel answer={answer} labelFor={labelFor} />}
            </div>
            <div
              className="min-w-0 rounded-lg border border-indigo-200 p-3 dark:border-indigo-900"
              data-testid="rerun-result"
            >
              <p className="mb-2 text-xs font-semibold">
                Expected way · {labelFor(rerun.end.dispatched_route)}
              </p>
              {rerun.answer && <AnswerPanel answer={rerun.answer} labelFor={labelFor} />}
              <div className="mt-3">
                <CostStripView strip={rerun.end.cost_strip} rerun />
              </div>
            </div>
          </div>
          <p className="mt-2 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-600 dark:bg-gray-950 dark:text-gray-400">
            This re-run was a forced route, not a routing outcome: it does not feed the agreement
            or latency history.
          </p>
        </div>
      ) : (
        answer && (
          <div className="mt-3 rounded-lg border border-indigo-200 p-3 dark:border-indigo-900">
            <AnswerPanel answer={answer} labelFor={labelFor} />
          </div>
        )
      )}
      {end && (
        <div className="mt-3">
          <CostStripView strip={end.cost_strip} />
        </div>
      )}
      {end && (
        <p data-testid="units" className="mt-2 text-xs text-gray-500">
          Model-call units: {end.units.reserved} reserved · {end.units.used} used ·{' '}
          {end.units.released} released · run time {(end.elapsed_ms / 1000).toFixed(2)} s
        </p>
      )}
      {onRerun && end && !rerun && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onRerun}
            disabled={busy}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50 dark:bg-indigo-400 dark:text-gray-950"
          >
            Run it the expected way
          </button>
          <span className="text-xs text-gray-500">
            via {labelFor(decision.expected_route ?? end.dispatched_route)} · costs 1 run · router
            overhead 0 · not counted in history
          </span>
        </div>
      )}
    </article>
  )
}

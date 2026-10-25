// Built with Spec4 AI - https://spec4.ai
import type { Agreement, DecisionEvent, RouteId } from '../../api/router'

/** Props for {@link DecisionCard}. */
export interface DecisionCardProps {
  decision: DecisionEvent
  /** Display label for a route id, from the generated route descriptions. */
  labelFor: (route: RouteId) => string
  /** Route ids in cost order, so the score bars sit in a stable order. */
  costOrder: RouteId[]
}

const AGREEMENT_TEXT: Record<Agreement, string> = {
  agreed: 'agreed with expected route',
  misrouted: 'misrouted',
  declined: 'declined — the router did not choose',
}

const AGREEMENT_STYLE: Record<Agreement, string> = {
  agreed: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300',
  misrouted: 'bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300',
  declined: 'bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
}

/**
 * `Router Decision and Answer Card` (the decision half).
 *
 * **All four scores, on every decision that has them**, so a visitor can see
 * how close a confident decision was. They are shown as 0–1 bars with two
 * decimals — never as percentages — and labelled as the router's uncalibrated
 * self-report. The rationale is model text and is rendered as plain text: React
 * escapes it, and nothing here interprets markup.
 */
export function DecisionCard({ decision, labelFor, costOrder }: DecisionCardProps) {
  const torn: RouteId[] = decision.low_confidence?.torn ?? []
  const heading =
    decision.decision_kind === 'low_confidence' ? 'Low-confidence card' : 'Routed answer'

  return (
    <div data-testid="decision-card" className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{heading}</h3>
        {decision.agreement ? (
          <span
            data-testid="agreement"
            className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${AGREEMENT_STYLE[decision.agreement]}`}
          >
            {AGREEMENT_TEXT[decision.agreement]}
          </span>
        ) : (
          decision.expected_route === null && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-semibold text-gray-600 dark:bg-gray-800 dark:text-gray-400">
              free text · no history credit
            </span>
          )
        )}
      </div>

      {decision.low_confidence && (
        <p
          data-testid="low-confidence-caveat"
          className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-300"
        >
          {decision.low_confidence.caveat}
        </p>
      )}

      {decision.malformed_note && (
        <p
          data-testid="malformed-note"
          className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-300"
        >
          {decision.malformed_note}
        </p>
      )}

      {decision.evaluator_fallback_note && (
        <p
          data-testid="evaluator-fallback"
          className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-300"
        >
          {decision.evaluator_fallback_note}
        </p>
      )}

      {decision.scores && (
        <div className="rounded-lg border border-gray-200 p-3 dark:border-gray-800">
          <h4 className="mb-2 font-mono text-xs uppercase tracking-wide text-gray-500">
            Router decision
          </h4>
          <ul aria-label="Route scores" className="grid gap-1.5">
            {costOrder.map((route) => {
              const score = decision.scores?.[route] ?? 0
              const chosen = route === decision.chosen_route
              const isTorn = torn.includes(route)
              return (
                <li
                  key={route}
                  data-testid={`score-${route}`}
                  className={`grid grid-cols-[minmax(110px,170px)_1fr_40px] items-center gap-2 text-sm ${
                    chosen ? 'font-semibold text-indigo-700 dark:text-indigo-300' : ''
                  }`}
                >
                  <span>
                    {chosen ? '▶ ' : ''}
                    {labelFor(route)}
                  </span>
                  <span className="h-2 overflow-hidden rounded bg-gray-100 dark:bg-gray-800">
                    <span
                      className={`block h-full rounded ${
                        chosen ? 'bg-indigo-500' : isTorn ? 'bg-amber-500' : 'bg-gray-400'
                      }`}
                      style={{ width: `${Math.round(score * 100)}%` }}
                    />
                  </span>
                  <span className="text-right font-mono">{score.toFixed(2)}</span>
                </li>
              )
            })}
          </ul>
          {decision.rationale && (
            <p className="mt-2 text-sm">
              <span className="font-semibold">Rationale: </span>
              <span data-testid="rationale">{decision.rationale}</span>
            </p>
          )}
          <p className="mt-1 text-xs text-gray-500">
            Scores are the router&apos;s uncalibrated self-report, not probabilities.
            {decision.agreement === 'misrouted' && decision.expected_route && (
              <>
                {' '}
                Expected route: {labelFor(decision.expected_route)} — {decision.expected_reason}
              </>
            )}
          </p>
        </div>
      )}
    </div>
  )
}

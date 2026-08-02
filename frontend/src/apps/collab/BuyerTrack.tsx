// Built with Spec4 AI - https://spec4.ai
import { Markdown } from '../../components/Markdown'
import type { RunState } from './runState'

/**
 * The buyer's sequential lane: the request, the two counters, the award.
 *
 * Sequential where the sellers are parallel, and the contrast is the point —
 * the buyer's steps genuinely depend on each other (it cannot counter before
 * it has both bids), while the sellers' do not.
 *
 * All model-produced prose goes through the shared `Markdown` wrapper and
 * never through `dangerouslySetInnerHTML`: this is an unauthenticated public
 * surface showing generated text.
 *
 * An award that failed reconciliation is shown **with a banner**, not hidden
 * and not corrected. The server does not overwrite the model's declared winner,
 * so neither does this — a rationale that does not follow from its own scoring
 * is exactly the "plausible-sounding lie" the check exists to expose.
 */

/** Props for {@link BuyerTrack}. */
export interface BuyerTrackProps {
  state: RunState
}

/**
 * Render the buyer's track.
 *
 * @param props - The current run state.
 * @returns The buyer lane, or null before a run starts.
 */
export function BuyerTrack({ state }: BuyerTrackProps) {
  if (state.requestText === '') {
    return null
  }

  return (
    <section
      data-testid="buyer-track"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        The buyer&rsquo;s track
      </h3>

      <details className="mt-3 rounded-xl border border-gray-200 bg-gray-50 p-3 dark:border-gray-800 dark:bg-gray-950">
        <summary className="cursor-pointer text-xs font-medium text-gray-700 dark:text-gray-300">
          Request for quotation — composed without a model call
        </summary>
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-gray-600 dark:text-gray-400">
          {state.requestText}
        </pre>
      </details>

      {state.counterOffers.length > 0 && (
        <div data-testid="counter-offers" className="mt-3 grid gap-3 md:grid-cols-2">
          {state.counterOffers.map((offer) => (
            <div
              key={offer.seller_id}
              className="rounded-xl border border-gray-200 bg-gray-50 p-3 dark:border-gray-800 dark:bg-gray-950"
            >
              <p className="font-mono text-[10px] uppercase tracking-wide text-gray-500">
                Counter to {offer.seller_id} · {offer.targeted_term}
              </p>
              <p className="mt-1 text-xs text-gray-800 dark:text-gray-200">{offer.ask}</p>
              <Markdown className="mt-1.5">{offer.justification}</Markdown>
            </div>
          ))}
          <p className="col-span-full text-[11px] text-gray-400 dark:text-gray-500">
            Two different letters, each arguing only from the buyer&rsquo;s own
            requirement. Neither mentions the other supplier — every outgoing message
            is checked against the rival&rsquo;s sealed position before it is sent.
          </p>
        </div>
      )}

      {state.award && (
        <div
          data-testid="award"
          className="mt-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4"
        >
          <p className="font-mono text-[11px] uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
            Awarded to {state.award.winner_id}
          </p>

          {!state.awardReconciled && (
            <div
              data-testid="reconciliation-banner"
              className="mt-2 rounded-lg border border-amber-500/50 bg-amber-500/10 p-3"
            >
              <p className="text-xs font-semibold text-amber-700 dark:text-amber-400">
                ⚠ The rationale did not reconcile with the weights
              </p>
              <p className="mt-1 text-xs leading-relaxed text-gray-700 dark:text-gray-300">
                {state.reconciliationNote} The buyer&rsquo;s own decision is shown
                unchanged rather than quietly replaced with the one its scores support
                — a corrected winner would hide that anything went wrong.
              </p>
            </div>
          )}

          <Markdown className="mt-2">{state.award.rationale}</Markdown>

          {state.award.priority_references.length > 0 && (
            <p className="mt-2 text-[11px] text-gray-500 dark:text-gray-400">
              Priorities leaned on: {state.award.priority_references.join(', ')}
            </p>
          )}
          {state.award.runner_up_note && (
            <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
              Runner-up: {state.award.runner_up_note}
            </p>
          )}

          {state.award.per_priority_scoring.length > 0 && (
            <details className="mt-3">
              <summary className="cursor-pointer text-[11px] text-gray-500 dark:text-gray-400">
                The buyer&rsquo;s own scoring, which it committed to before writing the
                rationale
              </summary>
              <table className="mt-2 w-full text-[11px]">
                <tbody>
                  {state.award.per_priority_scoring.map((score, index) => (
                    <tr
                      key={`${score.seller_id}-${score.priority}-${index}`}
                      className="border-b border-gray-100 last:border-0 dark:border-gray-800"
                    >
                      <td className="py-1 text-gray-600 dark:text-gray-400">
                        {score.seller_id}
                      </td>
                      <td className="py-1 text-gray-600 dark:text-gray-400">
                        {score.priority}
                      </td>
                      <td className="py-1 text-right font-mono text-gray-800 dark:text-gray-200">
                        {score.score}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
        </div>
      )}

      {state.phase === 'halted' && state.error && (
        <div
          data-testid="halted-banner"
          className="mt-4 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4"
        >
          <p className="text-sm font-semibold text-amber-700 dark:text-amber-400">
            The round stopped early
          </p>
          <p className="mt-1 text-sm leading-relaxed text-gray-700 dark:text-gray-300">
            {state.error.message}
          </p>
        </div>
      )}
    </section>
  )
}

// Built with Spec4 AI - https://spec4.ai
import type { DelegationDecision, Specialist } from '../../api/orchestrated'

/**
 * The coordinator's decision, and the go-ahead control.
 *
 * **This is the only place in the app that can start a dispatch.** No effect
 * anywhere calls it — the confirmation is what makes the fan-out deliberate,
 * and an auto-advance would leave the gate on screen while removing what it
 * does. The same rule the planning app's review panel is built on.
 *
 * A weak fit is surfaced rather than hidden. The coordinator is asked to say
 * when a question does not map cleanly onto any two of the four, and reporting
 * that honestly is more useful than a confident pairing that misleads — so the
 * caveat renders and the preset chips stay visible above as a sharper
 * alternative.
 */
export interface DelegationReviewProps {
  decision: DelegationDecision
  specialists: Specialist[]
  /** True once dispatch has begun, so the control cannot fire twice. */
  dispatched: boolean
  /** Set when the visitor has no runs left; disables the control. */
  blockedMessage: string | null
  onDispatch: () => void
}

function labelFor(specialists: Specialist[], id: string): string {
  return specialists.find((entry) => entry.id === id)?.displayName ?? id
}

function colourFor(specialists: Specialist[], id: string): string {
  return specialists.find((entry) => entry.id === id)?.color ?? '#8b5cf6'
}

/**
 * Render the delegation decision awaiting confirmation.
 *
 * @param props - The decision, roster, dispatch state and handler.
 * @returns The review panel.
 */
export function DelegationReview({
  decision,
  specialists,
  dispatched,
  blockedMessage,
  onDispatch,
}: DelegationReviewProps) {
  const weakFit = decision.fit_quality === 'weak'

  return (
    <section
      data-testid="delegation-review"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <p className="font-mono text-xs text-violet-600 dark:text-violet-400">
        ↳ fan-out planned: 2 of 4 roster specialists · {decision.model_call_count}-call budget
        reserved
      </p>

      <h3 className="mt-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
        Delegation decision — awaiting your go-ahead
      </h3>

      {weakFit ? (
        <p
          data-testid="weak-fit-notice"
          className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200"
        >
          ⚠ The coordinator judged this a <strong>weak fit</strong>: the question does not map
          cleanly onto any two of these four specialists, so the pairing below is a best-effort
          approximation. The curated questions above produce sharper pairings.
        </p>
      ) : null}

      <p className="mt-3 text-sm leading-relaxed text-gray-700 dark:text-gray-300">
        <strong className="font-semibold text-gray-900 dark:text-gray-100">Rationale:</strong>{' '}
        {decision.rationale}
      </p>

      <h4 className="mt-4 mb-2 text-xs font-semibold tracking-wide text-gray-500 uppercase dark:text-gray-400">
        Distinct brief written for each specialist
      </h4>
      <ul className="space-y-2.5">
        {decision.briefs.map((brief) => (
          <li
            key={brief.specialist_id}
            data-testid={`brief-${brief.specialist_id}`}
            className="rounded-xl border border-gray-200 bg-gray-50 p-3 dark:border-gray-800 dark:bg-gray-950"
          >
            <p className="flex items-center gap-2 text-sm font-medium text-gray-900 dark:text-gray-100">
              <span
                aria-hidden="true"
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ backgroundColor: colourFor(specialists, brief.specialist_id) }}
              />
              {labelFor(specialists, brief.specialist_id)}
            </p>
            <p className="mt-1.5 text-xs leading-relaxed text-gray-600 dark:text-gray-400">
              {brief.instruction}
            </p>
          </li>
        ))}
      </ul>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          data-testid="dispatch-button"
          disabled={dispatched || blockedMessage !== null}
          onClick={onDispatch}
          className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Dispatch both specialists (2 parallel calls)
        </button>
        <span className="text-xs text-gray-500 dark:text-gray-500">
          Nothing runs until you confirm this delegation.
        </span>
      </div>

      {blockedMessage ? (
        <p
          role="status"
          className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200"
        >
          {blockedMessage}
        </p>
      ) : null}
    </section>
  )
}

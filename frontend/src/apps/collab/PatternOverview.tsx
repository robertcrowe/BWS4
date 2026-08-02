// Built with Spec4 AI - https://spec4.ai
/**
 * `collab_overview`, the half of it that is specific to *this demonstration*.
 *
 * The screen presents the overview in two static panels, and the split is
 * deliberate. The generic pattern explanation — peers rather than workers, the
 * contrast with orchestrated subagents, opacity enforced in code — lives in
 * `example-apps.ts` and is rendered directly above this by the shared
 * `PatternSummary`. This panel says the things that are true of *this build*
 * and would be wrong to state as properties of the pattern:
 *
 * - what a real cross-owner deployment would add, which is the honest
 *   counterweight to using A2A's data model without its transport;
 * - the candid note about single ownership and the staged trust boundary;
 * - the per-run call budget, which is a quota-conservation choice.
 *
 * Duplicating the pattern explanation here instead would repeat three
 * paragraphs the visitor has just read. This project has removed exactly that
 * duplicate twice — from the single-call screen and from chained calls — and
 * the established resolution is the one used here: the screen explains the
 * pattern from the catalogue, the app explains its own deployment.
 *
 * The candid note gets its own bordered block rather than a footnote because
 * the feature spec names "visitors take the staged trust boundary as a genuine
 * cross-organisation deployment" as a failure mode, with prominent placement as
 * the mitigation. Its styling *is* that mitigation, so it should not later be
 * demoted to small print.
 */

/** The fixed per-run model-call budget this deployment allows. */
export const CALL_BUDGET = 6

/**
 * Render the deployment-specific half of the overview.
 *
 * @returns The honesty-and-limits panel.
 */
export function PatternOverview() {
  return (
    <section
      data-testid="collab-overview"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        How this demonstration is simplified
      </h3>

      <p className="mt-2 text-sm leading-relaxed text-gray-600 dark:text-gray-400">
        The exchanges here use the{' '}
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          data model and interaction pattern of the A2A collaboration protocol
        </strong>{' '}
        — inspectable identity cards, peer task and message objects with an explicit sender and
        recipient, and work items attached to each message — but{' '}
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          without its network transport
        </strong>
        . The agents hand each other Python objects in one process. A real cross-owner deployment
        would add a transport binding so the parties can be separate services, agent discovery over{' '}
        <code className="rounded bg-gray-100 px-1 py-0.5 font-mono text-xs text-gray-700 dark:bg-gray-800 dark:text-gray-300">
          /.well-known/agent-card.json
        </code>{' '}
        so a party can find a peer it was not compiled alongside, and real authentication between
        owners — per-party credentials and signed messages.
      </p>

      <div className="mt-4 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4">
        <p className="text-sm leading-relaxed text-gray-700 dark:text-gray-300">
          <strong className="font-semibold text-amber-700 dark:text-amber-400">Candidly:</strong>{' '}
          all three agents here ship in{' '}
          <strong className="font-semibold text-gray-900 dark:text-gray-100">
            one BWS4 repository under one owner
          </strong>
          , so the trust boundary is <em>staged for teaching</em> rather than genuinely
          cross-organisational. And for a purchase this simple, a peer negotiation between
          autonomous agents would be{' '}
          <strong className="font-semibold text-gray-900 dark:text-gray-100">
            over-engineering in a real system
          </strong>{' '}
          — the pattern earns its keep when the parties really are separate and really do hold
          information the others must not see.
        </p>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-gray-600 dark:text-gray-400">
        To conserve shared usage, each run will use a fixed budget of{' '}
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          {CALL_BUDGET} model calls
        </strong>{' '}
        (2 opening bids + 2 counter-offers + 2 best-and-final bids — the request for quotation is
        composed without a model call), and runs are bounded by the showcase-wide hourly limit
        every example here shares. The pattern itself supports any number of agents and rounds;
        these limits are a quota-conservation choice for this demonstration, not a property of the
        pattern.
      </p>
    </section>
  )
}

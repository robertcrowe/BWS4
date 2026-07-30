// Built with Spec4 AI - https://spec4.ai
interface ChainBudgetNoticeProps {
  /**
   * The server's sentence about why this demo is capped at two calls. Passed in
   * rather than written here so the number the visitor reads is the number the
   * backend actually reserves budget for.
   */
  lengthNote: string
}

/**
 * Why this demo stops at two calls — and that stopping there is the demo's
 * choice, not the pattern's limit.
 *
 * A separate statement from the pattern explanation, which lives in the shared
 * directory and renders through `PatternSummary` above this component. This one
 * is here because it is a fact about *this deployment's budget*, sourced from
 * the backend that enforces it, and it would go stale in the directory the
 * moment the reservation changed.
 *
 * Replaced an in-app card that also explained the pattern. Two explanations of
 * one pattern on one screen is a duplicate, and the single-call screen already
 * had that duplicate removed for the same reason.
 */
export function ChainBudgetNotice({ lengthNote }: ChainBudgetNoticeProps) {
  return (
    <section
      aria-label="Why this demo runs exactly two calls"
      className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5"
    >
      <h2 className="mb-2 font-mono text-xs uppercase tracking-wide text-gray-500">
        Chain length · fixed at two
      </h2>
      <p
        data-testid="quota-notice"
        className="text-[13.5px] leading-relaxed text-gray-600 dark:text-gray-400"
      >
        {lengthNote}
      </p>
      <p className="mt-2.5 text-[13.5px] leading-relaxed text-gray-600 dark:text-gray-400">
        The two calls are independent requests. The critic never sees your original idea and never
        watches the writer draft anything — it receives a finished story and nothing else, which is
        what stops the second step from being coloured by how the first one went about its work.
      </p>
    </section>
  )
}

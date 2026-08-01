// Built with Spec4 AI - https://spec4.ai
/**
 * The non-AI educational panel: what orchestrated subagents are, and why the
 * numbers on this screen are what they are.
 *
 * Two things it has to say, and the second matters as much as the first. The
 * pattern is that a coordinator briefs independent workers who can run *at the
 * same time* because neither needs the other's output. The limits — three model
 * calls, three runs an hour — are this deployment conserving a shared free
 * tier, **not** a property of the pattern. Leaving that unsaid would teach a
 * developer that fan-out is inherently a two-agent affair.
 */

/**
 * Render the pattern explanation.
 *
 * @returns The overview panel.
 */
export function PatternOverview() {
  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900">
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        What is the orchestrated-subagents pattern?
      </h3>
      <p className="mt-2 text-sm leading-relaxed text-gray-600 dark:text-gray-400">
        Subagents are independent workers. A coordinator decides who should work on what
        and writes each of them a brief, and — because neither subagent depends on the
        other&rsquo;s output — <strong className="font-semibold text-gray-800 dark:text-gray-200">
        they can run at the same time</strong>. That is the fan-out. When both finish, a
        merge step reconciles their answers into one, which is the fan-in.
      </p>
      <p className="mt-3 text-sm leading-relaxed text-gray-600 dark:text-gray-400">
        To conserve shared usage, each run here uses a fixed budget of{' '}
        <strong className="font-semibold text-gray-800 dark:text-gray-200">3 model calls</strong>{' '}
        (1 coordinator + 2 specialists, with the merge folded into the coordinator&rsquo;s
        closing turn), and you get{' '}
        <strong className="font-semibold text-gray-800 dark:text-gray-200">3 runs per hour</strong>.
        The pattern itself supports any number of agents — these limits are a
        quota-conservation choice for this demonstration, not a property of the pattern.
      </p>
    </section>
  )
}

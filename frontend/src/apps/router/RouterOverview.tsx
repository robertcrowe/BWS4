// Built with Spec4 AI - https://spec4.ai
import { Link } from 'react-router'

import { exampleApps } from '../../data/example-apps'
import { ROUTER_RUN_CAP } from './runAllowance'

/**
 * The Router's educational overview: what a visitor learns before running.
 *
 * Follows the ReAct app's split: the generic pattern explanation lives in
 * `example-apps.ts` and is rendered above this by the shared `PatternSummary`;
 * this panel carries what is true of *this demonstration* — the contrasts with
 * sibling examples, the honest statement about what the scores are, the
 * statement that routing is not a tier of its own, and the limits.
 *
 * Every required statement is asserted by `router-overview.test.tsx`, because
 * each one is a claim the page makes and a drift would make it false.
 */

/** Look up a sibling example's route from the shared catalogue. */
function routeFor(appId: string): string {
  return exampleApps.find((app) => app.id === appId)?.route ?? '/'
}

const LINK = 'font-medium text-indigo-700 underline decoration-dotted dark:text-indigo-300'
const STRONG = 'font-semibold text-gray-800 dark:text-gray-200'
const PARA = 'mt-3 text-sm leading-relaxed text-gray-600 dark:text-gray-400'

/**
 * Render the Router's educational overview.
 *
 * @returns The overview panel.
 */
export function RouterOverview() {
  return (
    <section
      data-testid="router-overview"
      aria-labelledby="router-overview-heading"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <h2
        id="router-overview-heading"
        className="text-sm font-semibold text-gray-900 dark:text-gray-100"
      >
        What does a router do?
      </h2>

      <p className="mt-2 text-sm leading-relaxed text-gray-600 dark:text-gray-400">
        A request should be answered by{' '}
        <strong className={STRONG}>the cheapest path that can answer it well</strong>. A
        calculation needs no model at all; a rewrite needs one call but no outside facts; a
        question about the space dataset needs retrieval; only a time-sensitive question needs a
        live web search. Sending everything down the heaviest path wastes calls and time on the
        requests that never needed it.
      </p>

      <p className={PARA}>
        <strong className={STRONG}>The decision is a separate, small call</strong> rather than a
        capability of a bigger one: one cheap classification call reads the request, scores the
        four paths and stops. Ordinary code then dispatches to the chosen path. Keeping the
        decision small and separate is what makes it cheap, inspectable and testable — you can see
        exactly what it was told, what it chose and how often it agrees with the expected route.
      </p>

      <p className={PARA}>
        Unlike{' '}
        <Link to={routeFor('tool_use_integration')} className={LINK}>
          the Tool-Use example
        </Link>
        , where one model decides whether to call a tool inside its own turn and then reads the
        result, <strong className={STRONG}>the router emits a label and stops</strong> — it never
        sees the result of the route it chose. And unlike{' '}
        <Link to={routeFor('planning_agent_example_app')} className={LINK}>
          the Planning-Agent
        </Link>{' '}
        and{' '}
        <Link to={routeFor('react_loop_example_app')} className={LINK}>
          ReAct-Loop
        </Link>{' '}
        examples, where one model keeps control across several steps,{' '}
        <strong className={STRONG}>no step follows the dispatch</strong>: one decision, then code
        takes over.
      </p>

      <p className={PARA}>
        <strong className={STRONG}>
          The four scores on each decision card are the model&apos;s uncalibrated self-report
        </strong>{' '}
        — a ranking, not probabilities. The one calibrated number on this page is the{' '}
        <strong className={STRONG}>measured agreement rate with expected routes</strong>, shown in
        the agreement history below.
      </p>

      <p className={PARA}>
        <strong className={STRONG}>Routing is not a tier in Spec4&apos;s pattern library</strong>,
        and this app does not claim one. The decision is a single call (tier 03) with the
        structured_outputs mechanism attached, so it returns a typed object; everything after it is
        deterministic dispatch to paths whose tiers are already cited elsewhere in this gallery.
      </p>

      <p className={PARA} data-testid="router-limits">
        <strong className={STRONG}>Limits.</strong> To conserve shared quota, each run costs at
        most 2 model-call units — 1 on the deterministic route, 2 on the others — plus one Exa
        search on the search route. Both units are reserved before the router runs, and the second
        is released as soon as the evaluator accepts. You get {ROUTER_RUN_CAP} runs per visit,
        counted on screen; a comparison re-run counts as one of them. That is this app&apos;s own
        limit. Separately, every example app draws on the showcase&apos;s shared hourly cap, and a
        run the shared cap cannot cover is refused before it starts and costs none of your runs.
        This demo routes among four paths; routers in general can choose among any number of
        paths.
      </p>
    </section>
  )
}

// Built with Spec4 AI - https://spec4.ai
import { Link } from 'react-router'

import { exampleApps } from '../../data/example-apps'

/**
 * `react_overview`: what a visitor learns without pressing Start.
 *
 * The screen presents the overview in two panels, the split this project has
 * settled on twice before: the generic pattern explanation lives in
 * `example-apps.ts` and is rendered above this by the shared `PatternSummary`,
 * so the landing card and the screen describe the pattern in one set of words.
 * This panel carries what is true of *this demonstration* — the two contrasts
 * drawn against sibling examples in this gallery, the honest caveat about
 * presets 4 and 5, the two endings, and the run's cost.
 *
 * **Both contrasts are the reason this app exists**, so neither is optional
 * copy. Against Tool Use: there the model makes a single decision about whether
 * to search. Against Planning Agent: there a whole plan is fixed and approved
 * before anything runs. This app is the third position — decide again after
 * every observation, commit to nothing in advance.
 *
 * Route targets come from `example-apps.ts` rather than literal strings, so a
 * route rename moves the links with it.
 */

/** Look up a sibling example's route from the shared catalogue. */
function routeFor(appId: string): string {
  return exampleApps.find((app) => app.id === appId)?.route ?? '/'
}

/**
 * Render the ReAct Loop's educational overview.
 *
 * @returns The overview panel.
 */
export function PatternOverview() {
  return (
    <section
      data-testid="react-overview"
      aria-labelledby="react-overview-heading"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <h2
        id="react-overview-heading"
        className="text-sm font-semibold text-gray-900 dark:text-gray-100"
      >
        What is the reason–act–observe loop?
      </h2>

      <p className="mt-2 text-sm leading-relaxed text-gray-600 dark:text-gray-400">
        In an interleaved loop the agent never commits to a plan. It produces a
        short <strong className="font-semibold text-gray-800 dark:text-gray-200">thought</strong>,
        takes one <strong className="font-semibold text-gray-800 dark:text-gray-200">action</strong>{' '}
        — issue a search, or declare it can now answer — reads the{' '}
        <strong className="font-semibold text-gray-800 dark:text-gray-200">observation</strong>{' '}
        that action returned, and only then thinks again with that observation in
        hand. The second query is written only after the first result has been
        read, which is exactly what makes a multi-hop question answerable at all.
      </p>

      <p className="mt-3 text-sm leading-relaxed text-gray-600 dark:text-gray-400">
        It is more than{' '}
        <Link
          to={routeFor('tool_use_integration')}
          className="font-medium text-violet-700 underline decoration-dotted dark:text-violet-400"
        >
          the Tool-Use example
        </Link>
        , where the model makes <em>a single decision about whether to search</em>{' '}
        and then answers. Here that decision is made afresh on every cycle: search
        again, or stop and answer.
      </p>

      <p className="mt-3 text-sm leading-relaxed text-gray-600 dark:text-gray-400">
        And it is the opposite commitment point from{' '}
        <Link
          to={routeFor('planning_agent_example_app')}
          data-testid="react-planning-crossref"
          className="font-medium text-violet-700 underline decoration-dotted dark:text-violet-400"
        >
          the Planning-Agent example
        </Link>
        , where a full plan is fixed and shown to you for approval before any step
        runs. Here <strong className="font-semibold text-gray-800 dark:text-gray-200">no
        plan is shown up front and you approve nothing mid-run</strong> — each next
        step is chosen only after reading the previous result. Same pattern tier,
        opposite shape: plan-first commits before any observation exists; ReAct
        commits one step at a time.
      </p>

      <p className="mt-3 text-sm leading-relaxed text-gray-600 dark:text-gray-400">
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          Honest caveat:
        </strong>{' '}
        on the two more familiar presets — the Transformer paper&apos;s author and
        the director of <em>Spirited Away</em> — the model may state an early hop
        straight from its own knowledge and spend its searches where observation is
        genuinely needed. That is <em>correct</em> ReAct behaviour rather than a
        bug: an agent that searches for what it already knows is wasting its
        budget, and the trace showing the model choosing where observation is
        required is itself the teaching content. After each run every hop is
        labelled observed or recalled so you can see which was which.{' '}
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          Presets 1 to 3 are curated so that at least one demonstration has every
          hop visibly coming from an observation.
        </strong>
      </p>

      <p className="mt-3 text-sm leading-relaxed text-gray-600 dark:text-gray-400">
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          Every run ends in exactly one of two ways
        </strong>
        , and both are shown plainly. Either a{' '}
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          final answer
        </strong>{' '}
        naming the observations it drew on, or a{' '}
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          budget-exhausted
        </strong>{' '}
        card presenting the partial trace and saying what remained unresolved. The
        second is a designed outcome, not a malfunction — a loop free to choose its
        next step is free to run out of road, and dressing that up as an answer
        would be the dishonest option. Free-form questions are the likeliest to end
        that way.
      </p>
    </section>
  )
}

// Built with Spec4 AI - https://spec4.ai
import { Link } from 'react-router'

import { exampleApps } from '../../data/example-apps'

/**
 * The planning app's one v7 change: a pointer to its interleaved counterpart.
 *
 * **This is the entire diff to the planning agent in this revision** — copy and
 * one navigation link. No behaviour, route, schema, prompt, agent, budget or
 * test of that app is touched, and none should be while adding to this file.
 * The two apps sit in the same pattern tier and differ on exactly one axis, so
 * a visitor who has just watched a plan being approved is the right person to
 * be told there is a version that never makes one.
 *
 * A separate component rather than an edit to `example-apps.ts`, because the
 * shared `PatternSummary` renders its text as a plain string and the phase
 * requires a working router link. Widening `PatternSummary` to accept markup
 * would change a component eight other screens depend on, to solve a problem
 * one screen has.
 *
 * The target comes from the catalogue rather than a literal `/react`, so a route
 * rename moves this link with it.
 */

/**
 * Render the cross-reference to the ReAct Loop example.
 *
 * @returns The cross-reference panel.
 */
export function ReactCrossReference() {
  const reactRoute =
    exampleApps.find((app) => app.id === 'react_loop_example_app')?.route ?? '/'

  return (
    <section
      data-testid="planning-react-crossref"
      aria-label="The interleaved counterpart to this pattern"
      className="mt-4 rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900"
    >
      <h2 className="mb-1.5 font-mono text-xs uppercase tracking-wide text-gray-500">
        The other shape of this tier
      </h2>
      <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-400">
        This is the <strong className="font-semibold text-gray-800 dark:text-gray-200">plan-first</strong>{' '}
        shape of the planning-agent tier: the whole plan is fixed and shown to you
        for approval before any step runs. The contrasting shape is{' '}
        <strong className="font-semibold text-gray-800 dark:text-gray-200">
          interleaved reason–act–observe
        </strong>
        , where nothing is planned ahead — the agent thinks, takes one action, reads
        the observation, and only then decides its next step, with no approval asked
        for at any point. See the{' '}
        <Link
          to={reactRoute}
          data-testid="planning-react-link"
          className="font-medium text-violet-700 underline decoration-dotted dark:text-violet-400"
        >
          ReAct-Loop Example App
        </Link>{' '}
        for that shape beside this one: same tier, opposite commitment point.
      </p>
    </section>
  )
}

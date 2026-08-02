// Built with Spec4 AI - https://spec4.ai
import { CollabApp } from '../../apps/collab/CollabApp'
import { LayoutShell } from '../../components/LayoutShell'
import { PatternSummary } from '../../components/PatternSummary'

/**
 * screen-collab: the multi-agent collaboration app's route-level screen.
 *
 * Same screen/app split as every other example, and the same shared
 * `LayoutShell`, so a visitor arriving from the orchestrated screen finds the
 * nav, the theme toggle and the page frame exactly where they left them.
 *
 * `PatternSummary` renders the pattern explanation from `example-apps.ts`;
 * `CollabApp`'s own overview panel then covers what is specific to this
 * deployment. Neither repeats the other — see `apps/collab/PatternOverview`.
 *
 * Headline and intro copy track `.spec4/v6/design/mock.html`'s `#screen-collab`
 * section. The mock's third tag reads "2 runs per session"; this says the
 * showcase-wide hourly limit instead, because that is the gate the backend
 * actually applies — the stack spec is explicit that this app has no per-app
 * session counter.
 */
export function CollabScreen() {
  return (
    <LayoutShell>
      <div className="py-2">
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
            Pattern: Multi-Agent Collaboration (peer-to-peer)
          </span>
          <span className="rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            Scenario: Competitive procurement · 1 buyer vs 2 rival sellers
          </span>
          <span className="rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            Limits: 6 model calls per run · showcase-wide hourly cap
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
          Multi-Agent Collaboration Example App
        </h1>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          A buyer agent acting on your behalf runs one negotiation round against two rival seller
          agents that each hold private constraints the other cannot see. Opening bids and
          best-and-final bids run concurrently, the buyer counters each seller on a different
          term, and the award is explained against your stated priorities — then every hidden
          position is unsealed.
        </p>
        <PatternSummary appId="multi_agent_collaboration_example_app" />
      </div>

      <div className="mt-6">
        <CollabApp />
      </div>
    </LayoutShell>
  )
}

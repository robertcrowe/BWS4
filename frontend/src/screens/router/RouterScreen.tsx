// Built with Spec4 AI - https://spec4.ai
import { RouterApp } from '../../apps/router/RouterApp'
import { RouterOverview } from '../../apps/router/RouterOverview'
import { LayoutShell } from '../../components/LayoutShell'
import { PatternSummary } from '../../components/PatternSummary'

/**
 * screen-router: the Router app's route-level screen.
 *
 * Same screen/app split as every other example, and the same shared
 * `LayoutShell`, so the nav, the theme toggle and the page frame sit exactly
 * where they do on every other app.
 *
 * Headline and intro copy track `.spec4/v9/design/mock.html`'s Router section:
 * the header, then the overview, then the app (knowledge panel, request,
 * results, agreement history).
 */
export function RouterScreen() {
  return (
    <LayoutShell>
      <div className="py-2">
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3 py-1 font-mono text-xs text-gray-600 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400">
            <span className="h-1.5 w-1.5 rounded-full bg-indigo-400" />
            Pattern: Router
          </span>
          <span className="rounded-full border border-gray-200 bg-white px-3 py-1 font-mono text-xs text-gray-600 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400">
            Scenario: Four existing paths, one cheap decision
          </span>
          <span className="rounded-full border border-gray-200 bg-white px-3 py-1 font-mono text-xs text-gray-600 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400">
            Limits: ≤2 model-call units per run · 5 runs per visit
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">Router</h1>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          One cheap classification call decides the path; deterministic code dispatches and the
          model that decided takes no further part.
        </p>
        <PatternSummary appId="router_example_app" />
      </div>

      <div className="mt-6">
        <RouterOverview />
      </div>

      <div className="mt-6">
        <RouterApp />
      </div>
    </LayoutShell>
  )
}

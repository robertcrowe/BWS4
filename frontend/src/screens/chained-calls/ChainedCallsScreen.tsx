// Built with Spec4 AI - https://spec4.ai
import { ChainedCallsApp } from '../../apps/chained-calls/ChainedCallsApp'
import { LayoutShell } from '../../components/LayoutShell'
import { PatternSummary } from '../../components/PatternSummary'

/**
 * screen-chained: the chained-calls example app's route-level screen.
 *
 * Same screen/app split as the other example screens — the screen frames the
 * pattern inside the shared layout, the app owns the interaction. Headline and
 * intro copy track .spec4/v3/design/mock.html's `#screen-chained` section.
 *
 * Directory name matches `apps/chained-calls/`, following the newer
 * `single-call` convention rather than the older `tooluse` one, so both halves
 * of one app are found under the same name.
 *
 * The pattern explanation comes from `PatternSummary`, which reads the shared
 * `example-apps.ts` entry — so the landing directory's description of chained
 * calls and this screen's are the same sentence, not two that can drift. The
 * app's own `ChainBudgetNotice` states something different: why *this
 * deployment* runs exactly two of them.
 */
export function ChainedCallsScreen() {
  return (
    <LayoutShell>
      <div className="py-2">
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
            Pattern: Chained Calls (exactly 2 sequential calls)
          </span>
          <span className="rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            Roles: Struggling Writer → Harsh Critic
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
          Chained-Calls Example App
        </h1>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          Submit a short story idea. It&rsquo;s routed through two sequential model calls: a
          &ldquo;struggling writer&rdquo; persona drafts the story, then a &ldquo;harsh critic&rdquo;
          persona critiques that exact draft. Both the intermediate and final outputs stay visible,
          so the hand-off between steps is never hidden.
        </p>
        <PatternSummary appId="chained_calls_example_app" />
      </div>

      <div className="mt-6">
        <ChainedCallsApp />
      </div>
    </LayoutShell>
  )
}

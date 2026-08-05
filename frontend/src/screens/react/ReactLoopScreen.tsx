// Built with Spec4 AI - https://spec4.ai
import { ReactLoopApp } from '../../apps/react/ReactLoopApp'
import { LayoutShell } from '../../components/LayoutShell'
import { PatternSummary } from '../../components/PatternSummary'

/**
 * screen-react: the ReAct Loop app's route-level screen.
 *
 * Same screen/app split as every other example, and the same shared
 * `LayoutShell`, so a visitor arriving from the planning screen finds the nav,
 * the theme toggle and the page frame exactly where they left them.
 *
 * The phase instruction places this component under `apps/react/`; it is under
 * `screens/react/` because the repo's screen/app split is the stronger signal
 * and all eight existing apps follow it — the same divergence, for the same
 * reason, as `screens/planning/PlanningScreen.tsx`.
 *
 * `PatternSummary` renders the pattern explanation from `example-apps.ts`.
 * The app's own overview — the honest caveat about presets 4 and 5, the
 * two-runs-per-session rationale, and the cross-reference to the Planning Agent
 * example — is the `react_overview` surface and lands with the loop; putting a
 * second pattern explanation here now would be the in-app duplicate this repo
 * has removed twice (single call, chained calls).
 *
 * Headline and intro copy track `.spec4/v7/design/mock.html`'s `#screen-react`
 * section. The mock's third tag reads "3–6 cycles per run"; this says the
 * server-fixed budget instead, because the budget is not visitor-settable —
 * see the stack spec's `react_run_call_budget` decision.
 */
export function ReactLoopScreen() {
  return (
    <LayoutShell>
      <div className="py-2">
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3 py-1 font-mono text-xs text-gray-600 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400">
            <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
            Pattern: Interleaved Reason–Act–Observe (ReAct)
          </span>
          <span className="rounded-full border border-gray-200 bg-white px-3 py-1 font-mono text-xs text-gray-600 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400">
            Scenario: Multi-hop questions via live search
          </span>
          <span className="rounded-full border border-gray-200 bg-white px-3 py-1 font-mono text-xs text-gray-600 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-400">
            Limits: 8 search cycles per run · 2 runs per hour
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
          ReAct-Loop Example App
        </h1>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          Pick a multi-hop question — or write your own — and watch the loop run live. Each
          cycle the model thinks briefly, chooses either a web search or to answer, reads the
          observation that comes back, and only then decides its next step. Nothing is
          planned ahead and you approve nothing mid-run; the trace fills in as it goes, and
          the run ends either in a final answer or in an honest budget-exhausted card.
        </p>
        <PatternSummary appId="react_loop_example_app" />
      </div>

      <div className="mt-6">
        <ReactLoopApp />
      </div>
    </LayoutShell>
  )
}

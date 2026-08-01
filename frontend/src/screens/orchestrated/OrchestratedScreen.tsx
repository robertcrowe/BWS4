// Built with Spec4 AI - https://spec4.ai
import { OrchestratedApp } from '../../apps/orchestrated/OrchestratedApp'
import { LayoutShell } from '../../components/LayoutShell'

/**
 * screen-orchestrated: the orchestrated-subagents app's route-level screen.
 *
 * Same screen/app split as every other example: the screen frames the pattern
 * inside the shared layout, the app owns the interaction. Headline and intro
 * copy track `.spec4/v5/design/mock.html`'s `#screen-orchestrated` section.
 *
 * No `PatternSummary` yet: that reads `example-apps.ts`, and this app has no
 * directory entry until the phase that makes it worth opening from the
 * catalogue. Adding an entry now would advertise a placeholder.
 */
export function OrchestratedScreen() {
  return (
    <LayoutShell>
      <div className="py-2">
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
            Pattern: Orchestrated Subagents (fan-out / fan-in)
          </span>
          <span className="rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            Roster: 4 knowledge-only specialists · exactly 2 chosen
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
          Orchestrated-Subagents Example App
        </h1>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          Ask a question. A coordinating agent picks exactly two of four fixed specialists, writes
          a distinct brief for each, and shows you that decision before anything is dispatched. On
          your go-ahead the two specialists run side by side — independently, at the same time —
          and their answers are then merged into one integrated response, with both source answers
          kept on screen.
        </p>
      </div>

      <div className="mt-6">
        <OrchestratedApp />
      </div>
    </LayoutShell>
  )
}

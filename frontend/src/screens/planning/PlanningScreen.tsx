// Built with Spec4 AI - https://spec4.ai
import { PlanningApp } from '../../apps/planning/PlanningApp'
import { LayoutShell } from '../../components/LayoutShell'
import { PatternSummary } from '../../components/PatternSummary'

/**
 * screen-planning: the planning-agent example app's route-level screen.
 *
 * Same screen/app split as every other example: the screen frames the pattern
 * inside the shared layout, the app owns the interaction. Headline and intro
 * copy track .spec4/v4/design/mock.html's `#screen-planning` section, and the
 * pattern explanation comes from the shared `PatternSummary` reading
 * `example-apps.ts`, so the landing directory and this screen describe the
 * pattern in the same words rather than in two that can drift.
 *
 * The limits tag states the per-run call ceiling and the per-session run cap
 * that Phases 2–4 enforce. It is written here from the start because the
 * feature's success criteria require both be communicated up front — but note
 * that until those phases land, the app below this intro runs no calls at all.
 */
export function PlanningScreen() {
  return (
    <LayoutShell>
      <div className="py-2">
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
            Pattern: Planning Agent
          </span>
          <span className="rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            Scenario: One-day trip planner
          </span>
          <span className="rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            Limits: 1 planner + up to 3 executor steps per run · 3 runs per day
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
          Planning-Agent Example App
        </h1>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          Give the agent a city and your interests. A planner call decomposes that fuzzy goal into
          a small, visible plan of discrete steps — web research plus one final synthesis. The plan
          is shown first; nothing executes until you explicitly give the go-ahead. Then executor
          calls run the steps in sequence, each result appearing as it completes, ending in a
          one-day itinerary.
        </p>
        <PatternSummary appId="planning_agent_example_app" />
      </div>

      <div className="mt-6">
        <PlanningApp />
      </div>
    </LayoutShell>
  )
}

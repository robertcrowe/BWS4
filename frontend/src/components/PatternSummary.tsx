// Built with Spec4 AI - https://spec4.ai
import { exampleApps } from '../data/example-apps'

interface PatternSummaryProps {
  /** The `id` of the entry in example-apps.ts whose summary to render. */
  appId: string
}

/**
 * Renders one example app's pattern summary beneath its screen intro.
 *
 * The text comes from example-apps.ts rather than being written into each
 * screen, keeping that file the single source of truth for what an example app
 * *is* — the landing directory and the screen itself can't drift apart.
 * Renders nothing if the id has no entry, so a screen never breaks over copy.
 */
export function PatternSummary({ appId }: PatternSummaryProps) {
  const app = exampleApps.find((candidate) => candidate.id === appId)

  if (!app) {
    return null
  }

  return (
    <section
      aria-label={`About the ${app.patternTag} pattern`}
      className="mt-4 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-4"
    >
      <h2 className="mb-1.5 font-mono text-xs uppercase tracking-wide text-gray-500">
        The pattern · {app.patternTag}
      </h2>
      <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-400">
        {app.patternSummary}
      </p>
    </section>
  )
}

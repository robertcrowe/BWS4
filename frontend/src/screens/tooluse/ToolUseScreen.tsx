// Built with Spec4 AI - https://spec4.ai
import { ToolUseApp } from '../../apps/tooluse/ToolUseApp'
import { LayoutShell } from '../../components/LayoutShell'

/**
 * screen-tooluse: the tool-use example app's route-level screen, framing the
 * app in the shared layout and explaining the pattern being demonstrated.
 */
export function ToolUseScreen() {
  return (
    <LayoutShell>
      <div className="py-2">
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-400" />
            Pattern: Tool Use / Function Calling
          </span>
          <span className="rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            Capability: Live search tool
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">Tool-Use Example App</h1>
        <p className="mt-2 max-w-2xl text-sm text-gray-600 dark:text-gray-400">
          The model is handed a <code className="font-mono">web_search</code> tool schema and runs
          a real function-calling loop: it decides whether the tool is needed, writes its own
          search query, reads the results, and may search again before answering. Every step below
          is what the model actually did — nothing is scripted.
        </p>
      </div>

      <div className="mt-6">
        <ToolUseApp />
      </div>
    </LayoutShell>
  )
}

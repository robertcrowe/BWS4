// Built with Spec4 AI - https://spec4.ai
import { RagApp } from '../../apps/rag/RagApp'
import { LayoutShell } from '../../components/LayoutShell'
import { PatternSummary } from '../../components/PatternSummary'

/**
 * screen-rag: the RAG example app's route-level screen, framing the app in
 * the shared layout and explaining the pattern being demonstrated.
 */
export function RagScreen() {
  return (
    <LayoutShell>
      <div className="py-2">
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-400" />
            Pattern: Retrieval-Augmented Generation
          </span>
          <span className="rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            Reference dataset: Space Exploration Facts
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">RAG Example App</h1>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          Ask a question and watch BWS4 retrieve supporting passages from a small public dataset,
          then generate an answer grounded in what it found. Both the retrieved passages and the
          generated answer are shown, so the retrieval → generation chain stays visible.
        </p>
        <PatternSummary appId="rag_example_app" />
      </div>

      <div className="mt-6">
        <RagApp />
      </div>
    </LayoutShell>
  )
}

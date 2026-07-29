// Built with Spec4 AI - https://spec4.ai
import { EmbeddingsApp } from '../../apps/embeddings/EmbeddingsApp'
import { LayoutShell } from '../../components/LayoutShell'
import { PatternSummary } from '../../components/PatternSummary'

/**
 * screen-embeddings: the embeddings example app's route-level screen.
 *
 * Follows the same screen/app split as the RAG and tool-use screens — the
 * screen frames the pattern in the shared layout, the app owns the
 * interaction. Headline and intro copy track .spec4/v1/design/mock.html's
 * `#screen-embeddings` section; Phase 4 fills in the plot beneath.
 */
export function EmbeddingsScreen() {
  return (
    <LayoutShell>
      <div className="py-2">
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-400" />
            Pattern: Text Embeddings
          </span>
          <span className="rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            Reference examples: 24 curated texts across 4 categories
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
          Embeddings Example App
        </h1>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          Every piece of text below has been converted into a numeric vector by the shared
          embedding model, then projected into 2D so semantically similar texts land near each
          other. The projection is fitted once, server-side, so the layout is the same every
          time you visit.
        </p>
        <PatternSummary appId="embeddings_example_app" />
      </div>

      <div className="mt-6">
        <EmbeddingsApp />
      </div>
    </LayoutShell>
  )
}

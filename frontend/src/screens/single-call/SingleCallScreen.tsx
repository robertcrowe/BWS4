// Built with Spec4 AI - https://spec4.ai
import { SingleCallApp } from '../../apps/single-call/SingleCallApp'
import { LayoutShell } from '../../components/LayoutShell'
import { PatternSummary } from '../../components/PatternSummary'

/**
 * screen-singlecall: the single-call example app's route-level screen.
 *
 * Same screen/app split as the RAG, tool-use, and embeddings screens — the
 * screen frames the pattern inside the shared layout, the app owns the
 * interaction. Headline and intro copy track .spec4/v2/design/mock.html's
 * `#screen-singlecall` section.
 *
 * Directory name matches `apps/single-call/` rather than the older
 * `screens/tooluse/` style, so both halves of one app are found under the
 * same name.
 */
export function SingleCallScreen() {
  return (
    <LayoutShell>
      <div className="py-2">
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            <span className="h-1.5 w-1.5 rounded-full bg-violet-400" />
            Pattern: Single-Call (no retrieval, no tools, no chaining)
          </span>
          <span className="rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            Modes: Simple &amp; Structured
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">
          Single-Call Example App
        </h1>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          The simplest agentic building block: one prompt goes in, one model response comes out —
          no retrieval, no external tools, no multi-step chaining. Toggle between a plain-text
          response and a schema-conforming structured response to see the same pattern rendered
          both ways.
        </p>
        <PatternSummary appId="single_call_example_app" />
      </div>

      {/* No width cap of its own: the app fills the same column as the intro
          and pattern summary above, matching how the RAG, tool-use, and
          embeddings screens lay out. LayoutShell's `max-w-5xl` is the single
          place the content width is decided. Structured mode benefits twice
          over — its request and response panes sit side by side. */}
      <div className="mt-6">
        <SingleCallApp />
      </div>
    </LayoutShell>
  )
}

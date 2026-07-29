// Built with Spec4 AI - https://spec4.ai
import { useState } from 'react'

import type { PlacementResult } from '../../api/embeddings'
import { useEmbeddingPresets } from '../../api/useEmbeddings'
import { CustomTextForm } from './CustomTextForm'
import { CATEGORY_COLORS, CUSTOM_POINT_COLOR, CUSTOM_TRACE_NAME, FALLBACK_COLOR } from './plotTraces'
import { SemanticPlot } from './SemanticPlot'

/**
 * The embeddings example app: the educational explanation alongside the
 * interactive semantic plot, matching the design mock's two-column
 * `#screen-embeddings` layout.
 *
 * Phase 5 adds the add-your-own-text form to the left column.
 */
export function EmbeddingsApp() {
  const { data: presets, isPending, isError, error, refetch, isFetching } = useEmbeddingPresets()

  // The visitor's most recent placement. Held here rather than read from the
  // mutation so the point survives while a *next* submission is in flight —
  // the plot should not blink empty between requests.
  const [placement, setPlacement] = useState<PlacementResult | null>(null)

  const categories = presets ? [...new Set(presets.map((preset) => preset.category))] : []

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[340px_1fr]">
      <div className="space-y-4">
        <ExplanationCard />
        {presets && <CustomTextForm onPlaced={setPlacement} />}
      </div>

      <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
        <div className="mb-1 flex items-baseline justify-between gap-3">
          <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            Semantic plot (2D projection)
          </h4>
          {presets && (
            <span className="font-mono text-xs text-gray-500">
              {presets.length} texts · {categories.length} categories
            </span>
          )}
        </div>
        <p className="mb-3 text-xs text-gray-500">
          Position is meaning, not wording. Hover a point to read its text; click a category in
          the legend to isolate it.
        </p>

        {isPending && (
          <p className="py-20 text-center text-sm text-gray-500">Loading the semantic plot…</p>
        )}
        {isError && (
          <div className="py-16 text-center">
            <p className="text-sm font-medium text-red-600 dark:text-red-400">
              Could not load the preset examples.
            </p>
            {/* The specific reason, not just the fact of failure — a blocked
                origin and a stopped backend look identical to `fetch`, and
                without this the two are indistinguishable from the screen. */}
            <p className="mx-auto mt-2 max-w-md text-xs text-gray-500">
              {error instanceof Error ? error.message : 'The request failed for an unknown reason.'}
            </p>
            {/* `staleTime: Infinity` means a query that failed once will not
                refetch on its own, so a backend started after the page loaded
                would leave this screen dead until a hard reload without an
                explicit way to try again. */}
            <button
              type="button"
              onClick={() => void refetch()}
              disabled={isFetching}
              className="mt-4 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3.5 py-2 text-sm text-gray-700 dark:text-gray-300 hover:border-violet-500 disabled:opacity-50"
            >
              {isFetching ? 'Retrying…' : 'Try again'}
            </button>
          </div>
        )}

        {presets && (
          <>
            <SemanticPlot presets={presets} customPlacement={placement} />
            <PlotFootnote hasCustomPoint={placement !== null} />
          </>
        )}
      </div>
    </div>
  )
}

function ExplanationCard() {
  return (
    <section className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
      <h4 className="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
        What is an embedding?
      </h4>
      <div className="space-y-3 text-[13.5px] leading-relaxed text-gray-600 dark:text-gray-400">
        <p>
          An embedding is a list of numbers a model produces from a piece of text, arranged so
          that texts with similar meaning get similar numbers. Nothing is generated and there is
          no answer to read — the output is a <em>position</em>.
        </p>
        <p>
          BWS4 uses one shared embedding model across every example app. The same model that
          scores passages in the RAG app placed every point here, so{' '}
          <span className="font-mono text-xs">joy</span> lands near{' '}
          <span className="font-mono text-xs">grief</span> and far from{' '}
          <span className="font-mono text-xs">database</span> — those two emotion words are
          opposites in sentiment, but both are about feeling, and that is what gets encoded.
        </p>
        <p>
          Notice that whole sentences land beside single words. A sentence about penguins sits
          among the animals rather than among the other sentences: length and phrasing are not
          what the representation captures.
        </p>
      </div>
    </section>
  )
}

function PlotFootnote({ hasCustomPoint }: { hasCustomPoint: boolean }) {
  return (
    <div className="mt-3 border-t border-gray-200 dark:border-gray-800 pt-3">
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1.5">
        {Object.entries(CATEGORY_COLORS).map(([category, color]) => (
          <span
            key={category}
            className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-400"
          >
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: color ?? FALLBACK_COLOR }}
              aria-hidden="true"
            />
            {category}
          </span>
        ))}
        {hasCustomPoint && (
          <span className="flex items-center gap-1.5 text-xs font-medium text-gray-700 dark:text-gray-300">
            {/* A rotated square — the same diamond the plot draws, so the
                legend key matches the marker rather than approximating it. */}
            <span
              className="h-2.5 w-2.5 rotate-45 border border-white"
              style={{ backgroundColor: CUSTOM_POINT_COLOR }}
              aria-hidden="true"
            />
            {CUSTOM_TRACE_NAME}
          </span>
        )}
      </div>
      <p className="text-xs text-gray-500">
        The axes are unlabelled on purpose. They are PCA components — the squeeze from 384
        dimensions down to 2 keeps under a fifth of the original detail, so distances here are
        indicative and only relative position carries meaning.
      </p>
    </div>
  )
}

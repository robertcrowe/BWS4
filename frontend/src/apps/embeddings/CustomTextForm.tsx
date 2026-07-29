// Built with Spec4 AI - https://spec4.ai
import { useState } from 'react'

import { MAX_CUSTOM_TEXT_CHARS, type PlacementResult } from '../../api/embeddings'
import { usePlaceCustomText } from '../../api/useEmbeddings'

/** Starting points, matching the design mock's suggestion chips. */
const SUGGESTIONS = ['sushi rolls', 'quantum computer', 'so much joy today', 'a swift red fox']

interface CustomTextFormProps {
  /** Called with each successful placement, so the plot can render the point. */
  onPlaced: (placement: PlacementResult) => void
}

/**
 * The add-your-own-text surface: input, suggestions, validation, and the
 * nearest-preset readout for the most recent submission.
 *
 * Validation runs here before the mutation fires, so blank input never costs
 * a round trip — the backend rejects it too, but a visitor should be told
 * immediately rather than after a network wait.
 */
export function CustomTextForm({ onPlaced }: CustomTextFormProps) {
  const [text, setText] = useState('')
  const [validationError, setValidationError] = useState<string | null>(null)
  const placement = usePlaceCustomText()

  function submit(raw: string) {
    const trimmed = raw.trim()

    if (!trimmed) {
      setValidationError('Enter some text to place on the plot.')
      return
    }
    if (trimmed.length > MAX_CUSTOM_TEXT_CHARS) {
      setValidationError(
        `That's ${trimmed.length} characters — the limit is ${MAX_CUSTOM_TEXT_CHARS}.`,
      )
      return
    }

    setValidationError(null)
    placement.mutate(trimmed, { onSuccess: onPlaced })
  }

  return (
    <section className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
      <h4 className="mb-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
        Add your own text
      </h4>
      <p className="mb-3 text-xs text-gray-500">
        It is embedded with the same model and projected into the same space — the existing points
        will not move.
      </p>

      <div className="mb-3 flex flex-wrap gap-1.5">
        {SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            disabled={placement.isPending}
            onClick={() => {
              setText(suggestion)
              submit(suggestion)
            }}
            className="rounded-full border border-gray-200 dark:border-gray-800 px-2.5 py-1 font-mono text-[11px] text-gray-600 dark:text-gray-400 hover:border-violet-500 disabled:opacity-50"
          >
            {suggestion}
          </button>
        ))}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault()
          // Guarded as well as disabled: the button is not the only way to
          // submit a form, and a second in-flight request is exactly the race
          // that could render points out of order.
          if (!placement.isPending) {
            submit(text)
          }
        }}
        className="flex gap-2"
      >
        <label className="sr-only" htmlFor="custom-text">
          Text to place on the plot
        </label>
        <input
          id="custom-text"
          type="text"
          value={text}
          onChange={(event) => {
            setText(event.target.value)
            if (validationError) {
              setValidationError(null)
            }
          }}
          placeholder="e.g. puppy, heartbreak, neural network..."
          aria-invalid={validationError ? true : undefined}
          aria-describedby={validationError ? 'custom-text-error' : undefined}
          className="min-w-0 flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 placeholder:text-gray-400 focus:border-violet-500 focus:outline-none"
        />
        <button
          type="submit"
          disabled={placement.isPending}
          className="shrink-0 rounded-lg bg-violet-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
        >
          {placement.isPending ? 'Placing…' : 'Add to plot'}
        </button>
      </form>

      {validationError && (
        <p id="custom-text-error" role="alert" className="mt-2 text-xs text-red-600 dark:text-red-400">
          {validationError}
        </p>
      )}

      {placement.isError && !validationError && (
        <div role="alert" className="mt-3 rounded-lg border border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/30 p-3">
          <p className="text-xs text-red-700 dark:text-red-300">
            {placement.error instanceof Error
              ? placement.error.message
              : 'Placing that text failed.'}
          </p>
          {/* Non-blocking by design: the plot keeps whatever it already shows,
              and the capability's escalation path is simply to let the visitor
              try again — this is a visualization, not a decision. */}
          <button
            type="button"
            onClick={() => submit(text)}
            disabled={placement.isPending}
            className="mt-2 rounded-md border border-red-300 dark:border-red-800 px-2.5 py-1 text-xs text-red-700 dark:text-red-300 hover:bg-red-100 dark:hover:bg-red-900/40 disabled:opacity-50"
          >
            Try again
          </button>
        </div>
      )}

      {placement.data && !placement.isError && (
        <NeighborReadout placement={placement.data} />
      )}
    </section>
  )
}

function NeighborReadout({ placement }: { placement: PlacementResult }) {
  return (
    <div className="mt-4 border-t border-gray-200 dark:border-gray-800 pt-3">
      <h5 className="mb-2 font-mono text-[11px] uppercase tracking-wide text-gray-500">
        Nearest presets to “{placement.text}”
      </h5>
      <ol className="space-y-1.5">
        {placement.nearest_neighbors.map((neighbor, index) => (
          <li
            key={neighbor.text}
            className="flex items-baseline justify-between gap-3 text-xs text-gray-600 dark:text-gray-400"
          >
            <span className="truncate">
              <span className="mr-1.5 font-mono text-gray-400">{index + 1}.</span>
              {neighbor.text}
            </span>
            <span className="shrink-0 font-mono text-gray-500">
              {neighbor.distance.toFixed(3)}
            </span>
          </li>
        ))}
      </ol>
      {/* Measured in the full 384-dimension space, not on the plot. Showing the
          number lets a visitor judge how confident the placement is: a tight
          0.2 means a real match, a flat 0.7-0.8 spread means the text did not
          really belong to any cluster. */}
      <p className="mt-2 text-[11px] leading-relaxed text-gray-500">
        Cosine distance in the full 384-dimension space, not the flattened plot. Lower is closer;
        a flat spread means your text did not land firmly in any category.
      </p>
    </div>
  )
}

// Built with Spec4 AI - https://spec4.ai
import { Markdown } from '../../components/Markdown'
import type { RunState } from './runState'

/**
 * `collab_priority_sensitivity`: what a different weighting would likely change.
 *
 * **The heading reads as a projection, and every part of the panel keeps that
 * frame.** This is the same recorded bids re-scored under different weights —
 * not a second negotiation. A real re-run would have started from a different
 * request, so the suppliers would have bid differently from the outset. Saying
 * "would have won" here would be asserting something about a world that does
 * not exist, which is why the server lints the narration for exactly those
 * verbs and why the caveat is a required field rather than a nicety.
 *
 * The two weightings are shown **side by side with the computed outcome**, so
 * the arithmetic is visible next to the prose explaining it. That is the whole
 * honesty of the panel: the flip was computed in application code and the model
 * only narrated it, so the visitor can see the sums the narration is about.
 */

const CONFIDENCE_TONE: Record<string, string> = {
  low: 'text-amber-600 dark:text-amber-400',
  medium: 'text-gray-600 dark:text-gray-400',
  high: 'text-emerald-600 dark:text-emerald-400',
}

/** Props for {@link SensitivityPanel}. */
export interface SensitivityPanelProps {
  state: RunState
}

function WeightColumn({
  label,
  weights,
  winner,
  highlight,
}: {
  label: string
  weights: Record<string, number>
  winner: string
  highlight: boolean
}) {
  return (
    <div
      className={`rounded-xl border p-3 ${
        highlight
          ? 'border-violet-500/40 bg-violet-500/5'
          : 'border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-gray-950'
      }`}
    >
      <p className="font-mono text-[10px] uppercase tracking-wide text-gray-500">{label}</p>
      <dl className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
        {Object.entries(weights).map(([axis, weight]) => (
          <div key={axis} className="contents">
            <dt className="text-gray-500">{axis}</dt>
            <dd className="text-right font-mono text-gray-700 dark:text-gray-300">
              {weight}
            </dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 border-t border-gray-200 pt-1.5 text-[11px] text-gray-700 capitalize dark:border-gray-800 dark:text-gray-300">
        → {winner === 'too_close' ? 'too close to call' : winner}
      </p>
    </div>
  )
}

/**
 * Render the priority-sensitivity projection.
 *
 * @param props - The current run state.
 * @returns The sensitivity panel, or null until the projection arrives.
 */
export function SensitivityPanel({ state }: SensitivityPanelProps) {
  const sensitivity = state.sensitivity
  if (!sensitivity) {
    return null
  }

  const computed = sensitivity.computed as
    | {
        original_weights?: Record<string, number>
        alternative_weights?: Record<string, number>
        alternative_label?: string
        original_winner?: string
        alternative_winner?: string
        outcome?: string
      }
    | undefined

  return (
    <section
      data-testid="sensitivity-panel"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          If the priorities had been different — a projection
        </h3>
        {sensitivity.fallback_generated && (
          <span
            data-testid="sensitivity-fallback-badge"
            className="rounded-full border border-amber-500/50 px-2 py-0.5 font-mono text-[10px] text-amber-600 dark:text-amber-400"
          >
            generated from the record, not written
          </span>
        )}
      </div>

      {computed?.original_weights && computed.alternative_weights && (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <WeightColumn
            label="As run"
            weights={computed.original_weights}
            winner={computed.original_winner ?? ''}
            highlight={false}
          />
          <WeightColumn
            label={computed.alternative_label ?? 'Alternative'}
            weights={computed.alternative_weights}
            winner={computed.alternative_winner ?? ''}
            highlight={computed.outcome === 'flipped'}
          />
        </div>
      )}

      <Markdown className="mt-3">{sensitivity.narration}</Markdown>

      <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px]">
        {sensitivity.decisive_dimensions.length > 0 && (
          <span data-testid="decisive-dimensions" className="text-gray-500">
            Terms that moved it: {sensitivity.decisive_dimensions.join(', ')}
          </span>
        )}
        <span
          data-testid="sensitivity-confidence"
          className={`font-mono ${CONFIDENCE_TONE[sensitivity.confidence] ?? 'text-gray-500'}`}
        >
          confidence: {sensitivity.confidence}
        </span>
      </div>

      <p
        data-testid="sensitivity-caveat"
        className="mt-3 border-t border-gray-100 pt-3 text-[11px] leading-relaxed text-gray-400 dark:border-gray-800 dark:text-gray-500"
      >
        {sensitivity.caveat}
      </p>
    </section>
  )
}

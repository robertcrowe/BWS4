// Built with Spec4 AI - https://spec4.ai
import type { AnnotationResult, HopAnnotation } from '../../api/react'

/**
 * `react_hop_annotations`: which facts observation actually supplied.
 *
 * **Additive, and silent when absent.** A run with no annotations renders the
 * trace exactly as it did before this panel existed — no error, no apology, no
 * empty state. Annotation is decorative: the model chain being down must cost a
 * badge, never the exhibit.
 *
 * **The copy says what this is.** These labels are an automated reading of the
 * trace, not a provenance guarantee: the server checks that a cited cycle
 * really searched and really returned snippets, but nothing verifies that the
 * snippet *supports* the claim — that would take another model call, and the
 * same limit is documented on the RAG app's citation audit.
 *
 * `all_hops_observed` may be stated here because it is **derived on the
 * server** from the annotations that survived its cross-checks. If the model
 * had asserted it, the panel could not.
 *
 * Every string here is model- or snippet-derived and renders as escaped text.
 */

/** Props for {@link AnnotationPanel}. */
export interface AnnotationPanelProps {
  annotations: AnnotationResult | null
  /** True when the run ended without an answer, which the heading says. */
  exhausted: boolean
}

const BADGE: Record<HopAnnotation['source'], string> = {
  observation: 'border-emerald-400 bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300',
  mixed: 'border-blue-400 bg-blue-50 text-blue-800 dark:bg-blue-950/50 dark:text-blue-300',
  model_knowledge: 'border-amber-400 bg-amber-50 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300',
}

// Distinguishable by wording as well as colour.
const LABEL: Record<HopAnnotation['source'], string> = {
  observation: 'observed',
  mixed: 'observed + recalled',
  model_knowledge: 'from memory',
}

/**
 * Render the hop-source panel, or nothing at all.
 *
 * @param props - The cross-checked annotations and how the run ended.
 * @returns The panel, or null when there is nothing to label.
 */
export function AnnotationPanel({ annotations, exhausted }: AnnotationPanelProps) {
  // Null and empty both render nothing. A visitor whose annotation call failed
  // sees the trace they already had, which is the whole point.
  if (annotations === null || annotations.hops.length === 0) {
    return null
  }

  return (
    <section
      data-testid="react-annotation-panel"
      aria-label="Hop source annotation"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        Hop source annotation
        {exhausted ? ' — run ended without an answer' : ''}
      </h3>

      <div className="mt-2 flex flex-wrap gap-2">
        <span
          data-testid="react-annotation-observed-count"
          className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 font-mono text-[11px] text-gray-700 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-300"
        >
          ✓ {annotations.observed_count} hop
          {annotations.observed_count === 1 ? '' : 's'} grounded in an observation
        </span>
        <span
          data-testid="react-annotation-recalled-count"
          className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1 font-mono text-[11px] text-gray-700 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-300"
        >
          {annotations.recalled_count} hop
          {annotations.recalled_count === 1 ? '' : 's'} recalled from the model&apos;s
          own knowledge
        </span>
      </div>

      {annotations.all_hops_observed && (
        <p
          data-testid="react-all-hops-observed"
          className="mt-2 rounded-lg border border-emerald-400 bg-emerald-50 p-2 text-xs text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200"
        >
          ✓ Every hop in this run came from an observation — checked against the
          trace, not taken from the model&apos;s word for it.
        </p>
      )}

      {exhausted && (
        <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
          This run spent its budget without answering. The hops below record only
          what was established along the way — they are not an answer.
        </p>
      )}

      <ul className="mt-3 space-y-2">
        {annotations.hops.map((hop) => (
          <li
            key={hop.cycle_index}
            data-testid={`react-hop-${hop.cycle_index}`}
            data-source={hop.source}
            className="flex flex-col gap-1.5 border-t border-dashed border-gray-200 pt-2 first:border-t-0 sm:flex-row sm:gap-3 dark:border-gray-800"
          >
            <span
              className={`h-fit w-fit shrink-0 rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide ${BADGE[hop.source]}`}
            >
              {LABEL[hop.source]}
            </span>
            <div className="min-w-0 text-xs">
              <strong className="text-gray-900 dark:text-gray-100">
                Cycle {hop.cycle_index}: {hop.fact}
              </strong>
              <p className="mt-0.5 text-gray-600 dark:text-gray-400">
                {hop.supporting_cycle !== null ? (
                  <>
                    Supplied by the{' '}
                    <a
                      href={`#react-cycle-${hop.supporting_cycle}`}
                      data-testid={`react-hop-link-${hop.cycle_index}`}
                      className="underline decoration-dotted"
                    >
                      cycle {hop.supporting_cycle} observation
                    </a>
                    .{' '}
                  </>
                ) : (
                  'No observation in this trace supplies it. '
                )}
                {hop.note}
              </p>
            </div>
          </li>
        ))}
      </ul>

      <p className="mt-3 text-[11px] text-gray-500 dark:text-gray-500">
        These labels are an automated reading of the trace above, not a verified
        provenance guarantee. A claim that a hop came from an observation is
        checked against whether that cycle really searched and really returned
        results — but nothing here verifies that the snippet supports the fact.
      </p>
    </section>
  )
}

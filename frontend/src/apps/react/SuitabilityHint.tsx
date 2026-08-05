// Built with Spec4 AI - https://spec4.ai
import type { QuestionSuitability } from '../../api/react'

/**
 * `react_suitability_check`: a hint beside the input. **Never a gate.**
 *
 * This component cannot disable anything. It takes no `onChange`, exposes no
 * callback, and the Start control's enabled state does not read its props —
 * which is the point rather than an accident. The capability's dominant risk is
 * that "suitability check" reads like a precondition, and an implementation
 * that disabled Start on a `single_hop` verdict would mean an upstream free-tier
 * outage silently closes the whole example.
 *
 * Five states, and the fifth is the one that matters most: `null` is the
 * neutral "we could not assess this" state that every server-side failure path
 * resolves to. It renders as a soft note, not an apology and not an error.
 *
 * `visitor_message` arrives already sanitised — markdown and tags stripped, a
 * URL or an over-long sentence replaced by a template keyed off the verdict —
 * so it is rendered as plain text here rather than through the markdown
 * wrapper. It is model-written prose about text the visitor typed, and the
 * fewer things that can happen to it on the way to the screen, the better.
 */

/** Props for {@link SuitabilityHint}. */
export interface SuitabilityHintProps {
  /** The verdict, or null for the neutral state. */
  verdict: QuestionSuitability | null
  /** True while the check is in flight. */
  checking: boolean
  /** True once a check has been attempted, so the neutral note is not shown early. */
  attempted: boolean
}

const TONE: Record<QuestionSuitability['verdict'], string> = {
  multi_hop_live: 'border-emerald-400 bg-emerald-50/60 dark:bg-emerald-950/30',
  multi_hop_static: 'border-blue-400 bg-blue-50/60 dark:bg-blue-950/30',
  single_hop: 'border-amber-400 bg-amber-50/60 dark:bg-amber-950/30',
  unanswerable: 'border-amber-400 bg-amber-50/60 dark:bg-amber-950/30',
}

const HEADLINE: Record<QuestionSuitability['verdict'], string> = {
  multi_hop_live: 'Looks like a good fit for the loop',
  multi_hop_static: 'Looks multi-hop, but answerable from stable facts',
  single_hop: 'Looks like a single lookup',
  unanswerable: 'This may not be answerable by search',
}

/**
 * Render the advisory beside the question input.
 *
 * @param props - The verdict and the check's progress.
 * @returns The hint, or nothing before a check has been attempted.
 */
export function SuitabilityHint({ verdict, checking, attempted }: SuitabilityHintProps) {
  if (checking) {
    return (
      <p
        data-testid="react-suitability-checking"
        className="mt-3 text-xs text-gray-500 dark:text-gray-400"
      >
        Checking whether this question will exercise the loop…
      </p>
    )
  }

  if (!attempted) {
    return null
  }

  if (verdict === null) {
    return (
      <p
        data-testid="react-suitability-unknown"
        className="mt-3 rounded-lg border border-gray-300 bg-gray-50 p-3 text-xs text-gray-600 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-400"
      >
        We couldn&apos;t assess this question up front — start the run and the
        trace will show what happens.
      </p>
    )
  }

  const hedged = verdict.confidence === 'low'

  return (
    <div
      data-testid="react-suitability-hint"
      data-verdict={verdict.verdict}
      className={`mt-3 rounded-lg border p-3 ${TONE[verdict.verdict]}`}
    >
      <p className="font-mono text-[10px] uppercase tracking-wide text-gray-600 dark:text-gray-400">
        {hedged ? `${HEADLINE[verdict.verdict]} — but we're not sure` : HEADLINE[verdict.verdict]}
      </p>
      <p className="mt-1 text-xs text-gray-800 dark:text-gray-200">
        {hedged ? `This is a low-confidence guess. ${verdict.visitor_message}` : verdict.visitor_message}
      </p>
      <p className="mt-1 text-[11px] text-gray-600 dark:text-gray-400">
        {verdict.estimated_hops} hop{verdict.estimated_hops === 1 ? '' : 's'}
        {verdict.requires_live_info && verdict.live_hop_description !== null
          ? ` · needs current information for ${verdict.live_hop_description}`
          : ' · no hop needs current information'}
      </p>
      {/* Said on every verdict, including the discouraging ones. This is a
          suggestion, and the copy has to make that unambiguous. */}
      <p className="mt-1.5 text-[11px] text-gray-500 dark:text-gray-500">
        This is only a suggestion — you can run it anyway.
      </p>
    </div>
  )
}

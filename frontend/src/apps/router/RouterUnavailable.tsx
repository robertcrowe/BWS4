// Built with Spec4 AI - https://spec4.ai
import { RUN_CAP } from './runAllowance'

/** The visitor-facing text. Fixed, so a failed retry cannot change it. */
export const UNAVAILABLE_MESSAGE =
  'The Router is temporarily unavailable: its route descriptions could not be prepared. No run can start until they are, and none of your runs is used meanwhile.'

/** Props for {@link RouterUnavailable}. */
export interface RouterUnavailableProps {
  /** Runs left this visit, shown unchanged while the Router is unavailable. */
  remaining: number
  onRetry: () => void
  /** True while a retry is in flight; the button is disabled. */
  pending: boolean
}

/**
 * Shown in place of the knowledge panel and the run controls while the route
 * descriptions are not ready.
 *
 * There is nothing to run against, so there is no input to type into. A failed
 * retry leaves this notice exactly as it was — no second banner — because the
 * situation it describes has not changed. The runs-remaining badge stays so
 * the visitor can see that waiting here costs nothing.
 */
export function RouterUnavailable({ remaining, onRetry, pending }: RouterUnavailableProps) {
  return (
    <section
      role="alert"
      aria-label="Router unavailable"
      data-testid="router-unavailable"
      className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-semibold">Router temporarily unavailable</p>
        <span
          data-testid="runs-remaining"
          className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-semibold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
        >
          Runs left {remaining} of {RUN_CAP}
        </span>
      </div>
      <p className="mt-1">{UNAVAILABLE_MESSAGE}</p>
      <button
        type="button"
        onClick={onRetry}
        disabled={pending}
        className="mt-3 rounded-md border border-amber-300 px-2.5 py-1 text-xs text-amber-900 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-amber-800 dark:text-amber-200 dark:hover:bg-amber-900/40"
      >
        {pending ? 'Retrying…' : 'Retry'}
      </button>
    </section>
  )
}

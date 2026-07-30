// Built with Spec4 AI - https://spec4.ai
import type { ChainResult } from '../../api/chainedCalls'
import { ChainedCallsRequestError } from '../../api/chainedCalls'

interface ChainResultViewProps {
  result: ChainResult
  onRetryCritique: () => void
  retryPending: boolean
  retryError: unknown
}

/**
 * The two labeled output blocks, and the partial state when only one exists.
 *
 * Both blocks are labeled by the role of the call that produced it, per the
 * feature's Outputs. The intermediate block renders identically whether the
 * chain finished or the critic failed — that is the point of the failure
 * mitigation: a result already generated is never discarded because a later
 * step went wrong.
 *
 * Layout tracks the mock's `.passages-block` for step 1 and `.answer-card` for
 * step 2, with the error variant carrying the retry.
 */
export function ChainResultView({
  result,
  onRetryCritique,
  retryPending,
  retryError,
}: ChainResultViewProps) {
  return (
    <div data-testid="chain-result" className="space-y-4">
      <IntermediateBlock result={result} />
      {result.final_output ? (
        <FinalBlock result={result} />
      ) : (
        <CritiqueFailed
          notice={result.notice}
          onRetry={onRetryCritique}
          pending={retryPending}
          error={retryError}
        />
      )}
    </div>
  )
}

/** `Step 1 · Struggling Writer` — call 1's output, and the literal input to call 2. */
function IntermediateBlock({ result }: { result: ChainResult }) {
  const { intermediate_output: intermediate } = result

  return (
    <section
      aria-labelledby="chain-step-1-heading"
      className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5"
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h3
          id="chain-step-1-heading"
          className="font-mono text-[11px] uppercase tracking-wide text-gray-500"
        >
          Step 1 · Struggling Writer (intermediate output)
        </h3>
        <Tag>{intermediate.role}</Tag>
        <Tag>{result.writer_model}</Tag>
      </div>

      {intermediate.title && (
        <p className="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
          {intermediate.title}
        </p>
      )}
      <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-gray-700 dark:text-gray-300">
        {intermediate.text}
      </p>
      <p className="mt-4 border-t border-gray-200 dark:border-gray-800 pt-3 text-xs text-gray-500">
        This text was sent to the second call as its entire input. The critic saw this and nothing
        else — not your story idea, and not the fact that a model wrote it.
      </p>
    </section>
  )
}

/** `Step 2 · Harsh Critic` — call 2's output, plus the evidence that it read call 1's. */
function FinalBlock({ result }: { result: ChainResult }) {
  const final = result.final_output
  if (!final) {
    return null
  }
  const signal = result.quality_signal

  return (
    <section
      aria-labelledby="chain-step-2-heading"
      className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5"
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h3
          id="chain-step-2-heading"
          className="font-mono text-[11px] uppercase tracking-wide text-gray-500"
        >
          Step 2 · Harsh Critic (final output)
        </h3>
        <Tag>{final.role}</Tag>
        {result.critic_model && <Tag>{result.critic_model}</Tag>}
      </div>

      {final.quoted_detail && (
        <blockquote className="mb-3 border-l-2 border-violet-400 bg-violet-50/60 dark:bg-violet-950/20 py-2 pl-3 text-[13px] italic leading-relaxed text-gray-700 dark:text-gray-300">
          {final.quoted_detail}
        </blockquote>
      )}
      <p className="whitespace-pre-wrap text-[13.5px] leading-relaxed text-gray-700 dark:text-gray-300">
        {final.text}
      </p>

      {signal && (
        <div className="mt-4 border-t border-gray-200 dark:border-gray-800 pt-3">
          <p className="text-xs text-gray-500">
            {signal.references_story ? (
              <>
                <span className="font-medium text-emerald-700 dark:text-emerald-400">
                  Quoted detail found in the story above.
                </span>{' '}
                The server checked that the phrase the critic quoted actually appears in the text
                the writer produced
                {signal.quoted_detail_found
                  ? ' word for word'
                  : ` as a close paraphrase (${Math.round(signal.match_ratio * 100)}% word match)`}
                .
              </>
            ) : (
              <>
                <span className="font-medium text-amber-700 dark:text-amber-400">
                  Quoted detail not found in the story above.
                </span>{' '}
                The critic named a detail the server could not locate in the writer&rsquo;s text, so
                this critique may be the generic kind that would fit any story.
              </>
            )}
          </p>
          <p className="mt-1.5 text-xs text-gray-400">
            That check establishes only that the quoted phrase is <em>present</em>. Nothing here has
            judged whether the critique is <em>right</em> — that would take a third model call, and
            this chain deliberately makes two.
          </p>
        </div>
      )}
    </section>
  )
}

/**
 * The `step2-failed-retryable` state.
 *
 * The retry re-sends only the second call. It is offered as a distinct action
 * from resubmitting because regenerating the story would produce a *different*
 * one, leaving the visitor with a critique of a draft they never read.
 */
function CritiqueFailed({
  notice,
  onRetry,
  pending,
  error,
}: {
  notice: string | null
  onRetry: () => void
  pending: boolean
  error: unknown
}) {
  const retryMessage =
    error instanceof ChainedCallsRequestError
      ? error.message
      : error instanceof Error
        ? error.message
        : null
  const capSpent = error instanceof ChainedCallsRequestError && error.code === 'usage_limit_reached'

  return (
    <section
      role="alert"
      className="rounded-2xl border border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/30 p-5"
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="font-mono text-[11px] uppercase tracking-wide text-red-700 dark:text-red-400">
          Step 2 · Harsh Critic — failed
        </h3>
      </div>
      <p className="text-sm text-red-700 dark:text-red-300">
        {notice ??
          'The second call did not complete. The story above is unchanged — an intermediate result is never discarded because a later step in the chain failed.'}
      </p>

      {retryMessage && (
        <p className="mt-2 text-xs text-red-700/90 dark:text-red-300/90">{retryMessage}</p>
      )}

      {/* Withheld when the budget is spent: retrying cannot succeed until 00:00
          UTC, and offering a button that is guaranteed to fail is worse than
          offering none. Same rule as the single-call screen. */}
      {!capSpent && (
        <button
          type="button"
          onClick={onRetry}
          disabled={pending}
          className="mt-3 rounded-md border border-red-300 dark:border-red-800 px-2.5 py-1 text-xs text-red-700 dark:text-red-300 hover:bg-red-100 disabled:opacity-50 dark:hover:bg-red-900/40"
        >
          {pending ? 'Retrying step 2…' : 'Retry step 2 only'}
        </button>
      )}
    </section>
  )
}

function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-full border border-gray-200 dark:border-gray-800 px-2.5 py-1 font-mono text-[11px] text-gray-600 dark:text-gray-400">
      {children}
    </span>
  )
}

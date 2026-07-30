// Built with Spec4 AI - https://spec4.ai
import { useState } from 'react'

import type { ChainResult } from '../../api/chainedCalls'
import {
  ChainedCallsRequestError,
  FALLBACK_PLAN,
  MAX_STORY_PROMPT_CHARS,
} from '../../api/chainedCalls'
import { useChainPlan, useRetryCritique, useRunChain } from '../../api/useChainedCalls'
import { ChainBudgetNotice } from './ChainBudgetNotice'
import { ChainResultView } from './ChainResultView'
import { ChainSteps } from './ChainSteps'
import type { RunPhase } from './chainState'
import { PRESET_STORY_PROMPTS } from './chainState'

/**
 * The chained-calls example app: two calls described up front, run in order,
 * both outputs shown.
 *
 * **The result lives in local state, not in the query cache.** Both API calls
 * are `useMutation`, and the completed chain is copied into `useState` here.
 * That is the phase's named risk handled at its root: a generation result has no
 * stable resource key, so anything caching it could resurface a previous run's
 * story against a new prompt — and in *this* app that failure is worse than
 * ordinary staleness, because the critique beside a stale story would have been
 * written about a different draft. `setResult(null)` on every submission means
 * no stale output can survive one.
 *
 * Layout follows .spec4/v3/design/mock.html's `#screen-chained`: chain-length
 * notice, input card with preset chips and the two-step indicator, then the
 * result panel. The pattern explanation is *not* here — it belongs to the
 * screen, which renders it through the shared `PatternSummary` from
 * `example-apps.ts`, so the landing directory and the screen cannot describe
 * the same pattern differently.
 */
export function ChainedCallsApp() {
  const plan = useChainPlan()
  const chain = useRunChain()
  const retry = useRetryCritique()

  const [prompt, setPrompt] = useState('')
  const [result, setResult] = useState<ChainResult | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)

  // The server's plan when it has arrived, the bundled copy until then. See
  // FALLBACK_PLAN: this backend sleeps when idle, and the roles must be
  // readable before the first request finishes, not after.
  const activePlan = plan.data ?? FALLBACK_PLAN
  const busy = chain.isPending || retry.isPending

  const phase: RunPhase = chain.isPending
    ? 'chain-running'
    : retry.isPending
      ? 'retry-running'
      : result?.status === 'complete'
        ? 'complete'
        : result?.status === 'critique_failed'
          ? 'critique-failed'
          : chain.isError
            ? 'blocked'
            : 'idle'

  function submit() {
    const trimmed = prompt.trim()

    if (!trimmed) {
      setValidationError('Enter a story idea before running the chain.')
      return
    }
    if (trimmed.length > MAX_STORY_PROMPT_CHARS) {
      setValidationError(
        `That story idea is ${trimmed.length} characters — the limit is ${MAX_STORY_PROMPT_CHARS}.`,
      )
      return
    }

    setValidationError(null)
    // Clear before the request, not after it resolves: the previous run's story
    // must not sit on screen underneath a spinner for the new one.
    setResult(null)
    retry.reset()
    chain.mutate({ storyPrompt: trimmed }, { onSuccess: setResult })
  }

  function retryCritiqueOnly() {
    if (!result) {
      return
    }
    // Only call 2 is re-sent, carrying the story already on screen — so the
    // critique that arrives is a critique of the draft the visitor is reading.
    retry.mutate({ intermediateOutput: result.intermediate_output }, { onSuccess: setResult })
  }

  return (
    <div className="space-y-4">
      <ChainBudgetNotice lengthNote={activePlan.length_note} />

      <section className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
        <h3 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">
          Write a story prompt
        </h3>

        <div className="mb-3.5 flex flex-wrap gap-2">
          {PRESET_STORY_PROMPTS.map((preset) => (
            <button
              key={preset}
              type="button"
              disabled={busy}
              onClick={() => {
                setPrompt(preset)
                setValidationError(null)
              }}
              className="rounded-full border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 px-3 py-1.5 text-left text-xs text-gray-600 hover:border-violet-500 disabled:opacity-50 dark:text-gray-400"
            >
              {preset}
            </button>
          ))}
        </div>

        <form
          onSubmit={(event) => {
            event.preventDefault()
            // Guarded as well as disabled: a form has more than one way to
            // submit, and a second chain in flight would spend two more units
            // of a shared daily budget.
            if (!busy) {
              submit()
            }
          }}
        >
          <label
            htmlFor="chained-story-prompt"
            className="mb-1.5 block font-mono text-[11px] uppercase tracking-wide text-gray-500"
          >
            Story idea
          </label>
          <input
            id="chained-story-prompt"
            type="text"
            value={prompt}
            onChange={(event) => {
              setPrompt(event.target.value)
              if (validationError) {
                setValidationError(null)
              }
            }}
            placeholder="e.g. a lonely lighthouse keeper who finds a message in a bottle"
            aria-invalid={validationError ? true : undefined}
            aria-describedby={validationError ? 'chained-story-prompt-error' : undefined}
            className="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-violet-500 focus:outline-none dark:text-gray-100"
          />

          <div className="mt-4 flex items-center justify-between gap-3">
            <span className="font-mono text-[11px] text-gray-400">
              {activePlan.chain_length} sequential calls, always in this order
            </span>
            <button
              type="submit"
              disabled={busy}
              className="shrink-0 rounded-lg bg-violet-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
            >
              {chain.isPending
                ? 'Running chain…'
                : `Run chain (${activePlan.chain_length} calls)`}
            </button>
          </div>
        </form>

        {validationError && (
          <p
            id="chained-story-prompt-error"
            role="alert"
            className="mt-2 text-xs text-red-600 dark:text-red-400"
          >
            {validationError}
          </p>
        )}

        <div className="mt-4 border-t border-gray-200 dark:border-gray-800 pt-4">
          <ChainSteps steps={activePlan.steps} phase={phase} />
        </div>
      </section>

      {chain.isPending && (
        // Deliberately indeterminate, and the copy says why. The whole chain is
        // one round trip, so the browser cannot know when call 1 hands off to
        // call 2 — animating that hand-off would be inventing an observation.
        <p className="flex items-center gap-2.5 font-mono text-xs text-gray-500">
          <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-gray-300 dark:border-gray-700 border-t-violet-500" />
          Running both calls in one round trip — the hand-off happens on the server, so both steps
          land at once.
        </p>
      )}

      {chain.isError && <ChainBlocked error={chain.error} onRetry={submit} />}

      {result && (
        <ChainResultView
          result={result}
          onRetryCritique={retryCritiqueOnly}
          retryPending={retry.isPending}
          retryError={retry.error}
        />
      )}
    </div>
  )
}

/**
 * The `quota-exhausted-before-start` and call-1-failed states.
 *
 * Both mean nothing was generated, so there is deliberately no partial output
 * here — the feature's mitigation is a clear message with "no partial or
 * misleading final output presented".
 *
 * Note which state is *absent*: the design mock has a `quota-exhausted-mid-chain`
 * card, showing a story with the critique refused. It cannot occur against this
 * backend, which reserves budget for both calls before running either — so a
 * chain that cannot finish never starts. Building the card anyway would mean
 * shipping a screen for a state the system cannot produce.
 */
function ChainBlocked({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const code = error instanceof ChainedCallsRequestError ? error.code : 'request_failed'
  const message =
    error instanceof Error ? error.message : 'The chain failed for an unknown reason.'
  const capSpent = code === 'usage_limit_reached'

  return (
    <section
      role="alert"
      className="rounded-2xl border border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/30 p-4"
    >
      <p className="text-sm font-medium text-red-700 dark:text-red-300">
        {capSpent
          ? 'The chain did not start — today’s shared generation budget cannot cover both calls.'
          : 'The chain did not complete.'}
      </p>
      <p className="mt-1 text-xs text-red-700/90 dark:text-red-300/90">{message}</p>
      {!capSpent && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-md border border-red-300 dark:border-red-800 px-2.5 py-1 text-xs text-red-700 hover:bg-red-100 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-900/40"
        >
          Try again
        </button>
      )}
    </section>
  )
}

// Built with Spec4 AI - https://spec4.ai
import { type FormEvent, useState } from 'react'

import type { AgentStep, SearchResult } from '../../api/tools'
import { useSearchMutation } from '../../api/useTools'
import { Markdown } from '../../components/Markdown'

const EXAMPLE_QUERIES = [
  'What is the latest Spec4 release?',
  'Current Mars rover mission status',
  'Recent breakthroughs in agentic AI frameworks',
  'What is 17 times 24?',
]

const STEP_STYLES: Record<AgentStep['kind'], { badge: string; accent: string }> = {
  decision: {
    badge: 'border-amber-500/40 text-amber-600 dark:text-amber-400',
    accent: 'text-amber-600 dark:text-amber-400',
  },
  tool_call: {
    badge: 'border-violet-500/40 text-violet-600 dark:text-violet-300',
    accent: 'text-violet-600 dark:text-violet-300',
  },
  tool_result: {
    badge: 'border-blue-500/40 text-blue-600 dark:text-blue-400',
    accent: 'text-blue-600 dark:text-blue-400',
  },
  answer: {
    badge: 'border-emerald-500/40 text-emerald-600 dark:text-emerald-400',
    accent: 'text-emerald-600 dark:text-emerald-400',
  },
}

/**
 * tool_use_search_demo surface: lets a visitor submit a question, then shows
 * the agent's real decision trace — whether it chose to call the search tool,
 * what query it wrote for itself, and what came back — alongside the answer it
 * produced from those results.
 */
export function SearchDemo() {
  const [query, setQuery] = useState('')
  const mutation = useSearchMutation()

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = query.trim()
    if (!trimmed) {
      return
    }
    mutation.mutate(trimmed)
  }

  return (
    <div>
      <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
        <h4 className="mb-1.5 text-sm font-semibold text-gray-900 dark:text-gray-100">
          Ask the agent a question
        </h4>
        <p className="mb-3.5 text-xs text-gray-600 dark:text-gray-400">
          The agent is given a <code className="font-mono">web_search</code> tool schema and
          decides for itself whether to use it — try one that needs a lookup and one that
          doesn&apos;t.
        </p>

        <div className="mb-4 flex flex-wrap gap-2">
          {EXAMPLE_QUERIES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setQuery(example)}
              className="rounded-full border border-gray-200 dark:border-gray-800 px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400 hover:border-violet-500 hover:text-gray-800 dark:hover:text-gray-200"
            >
              {example}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="flex gap-2.5">
          <input
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="e.g. What's the latest Spec4 release?"
            className="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 px-4 py-3 text-sm text-gray-900 dark:text-gray-100 focus:border-violet-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={mutation.isPending}
            className="rounded-lg bg-violet-500 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            Run agent
          </button>
        </form>
      </div>

      <div className="mt-5">
        {mutation.isPending && <RunningIndicator />}

        {mutation.isError && (
          <div role="alert" className="rounded-2xl border border-red-500/40 bg-white dark:bg-gray-900 p-5">
            <span className="mb-2 inline-block rounded-full border border-red-500/40 px-2.5 py-1 text-xs text-red-600 dark:text-red-400">
              Agent unavailable
            </span>
            <p className="text-sm text-gray-700 dark:text-gray-300">{mutation.error.message}</p>
          </div>
        )}

        {mutation.isSuccess && (
          <>
            <AgentTrace
              steps={mutation.data.steps}
              model={mutation.data.model}
              iterations={mutation.data.iterations}
            />
            <AnswerPanel
              answer={mutation.data.answer}
              results={mutation.data.results}
              queries={mutation.data.queries}
            />
          </>
        )}
      </div>
    </div>
  )
}

/**
 * Shown while the loop runs. Deliberately indeterminate: the agent's real
 * steps are only known once the round trip completes, and inventing an
 * animated sequence here would be exactly the theater this app replaced.
 */
function RunningIndicator() {
  return (
    <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
      <p className="font-mono text-xs text-violet-600 dark:text-violet-300">
        Agent running — deciding, searching, and composing an answer…
      </p>
      <div className="mt-3 h-1 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-800">
        <div className="h-full w-1/3 animate-pulse rounded-full bg-violet-500" />
      </div>
    </div>
  )
}

function AgentTrace({
  steps,
  model,
  iterations,
}: {
  steps: AgentStep[]
  model: string
  iterations: number
}) {
  return (
    <div className="mb-5 rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-2">
        <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Agent trace
        </h5>
        <span className="font-mono text-[11px] text-gray-500">
          {iterations} turn{iterations === 1 ? '' : 's'} · {model.replace('openrouter/', '')}
        </span>
      </div>

      <ol className="space-y-2.5">
        {steps.map((step, index) => (
          <li key={`${step.kind}-${index}`} className="flex gap-3">
            <span
              className={`mt-0.5 h-fit shrink-0 rounded-full border px-2.5 py-1 font-mono text-[11px] ${STEP_STYLES[step.kind].badge}`}
            >
              {String(index + 1).padStart(2, '0')}
            </span>
            <div className="min-w-0">
              <p className={`text-[13px] font-semibold ${STEP_STYLES[step.kind].accent}`}>
                {step.label}
              </p>
              <p className="break-words text-xs text-gray-600 dark:text-gray-400">{step.detail}</p>
            </div>
          </li>
        ))}
      </ol>

      {steps.every((step) => step.kind !== 'tool_call') && (
        <p className="mt-3.5 rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 p-3 text-xs text-gray-600 dark:text-gray-400">
          The model answered without calling the search tool. Choosing <em>not</em> to use a tool
          is as much a routing decision as choosing to use one.
        </p>
      )}
    </div>
  )
}

/**
 * Render a result's publish date, or say plainly that there isn't one.
 *
 * "Undated" rather than a blank: an empty slot reads as "recent" to a visitor
 * scanning a list, and the honest statement is that the search did not report
 * a date for this page.
 *
 * @param published - Exa's ISO date for the page, or null.
 * @returns A short date, or "undated".
 */
function formatPublished(published: string | null): string {
  if (!published) {
    return 'undated'
  }
  const parsed = new Date(published)
  return Number.isNaN(parsed.getTime()) ? 'undated' : parsed.toISOString().slice(0, 10)
}


function AnswerPanel({
  answer,
  results,
  queries,
}: {
  answer: string
  results: SearchResult[]
  queries: string[]
}) {
  return (
    <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
      {queries.length > 0 && (
        <p className="mb-3.5 font-mono text-xs text-blue-600 dark:text-blue-400">
          ↳ routed to: Search Tool — query written by the model:{' '}
          {queries.map((q) => `"${q}"`).join(', ')}
        </p>
      )}

      {/* `agent_v1.md` tells the model to write plain prose with no markdown,
          and models disregard that often enough to be worth rendering for.
          When they comply this is a no-op — the renderer keeps `pre-wrap`, so
          unformatted prose lays out exactly as it did before. */}
      <Markdown className="mb-5" variant="lead">
        {answer}
      </Markdown>

      {results.length > 0 && (
        <div>
          <h5 className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Sources the agent saw
          </h5>
          {results.map((result) => (
            <div
              key={`${result.rank}-${result.source}`}
              className="mb-2.5 rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-100 dark:bg-gray-800/40 p-3.5"
            >
              <div className="mb-1.5 flex items-center justify-between gap-2.5">
                <strong className="text-[13px] text-gray-900 dark:text-gray-100">
                  [{result.rank}] {result.title}
                </strong>
                {/* Relevance is not recency: the search ranks on relevance
                    alone, so an old page can come back first. Showing the date
                    is what lets a visitor tell a stale source from a stale
                    answer. */}
                <span
                  data-testid={`result-date-${result.rank}`}
                  className="shrink-0 font-mono text-[11px] text-gray-500"
                >
                  {formatPublished(result.published_date)}
                </span>
              </div>
              <p className="mb-1.5 text-xs text-gray-600 dark:text-gray-400">{result.summary}</p>
              <span className="rounded-md border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-950 px-2 py-0.5 font-mono text-[11px] text-gray-500">
                Source: {result.source}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

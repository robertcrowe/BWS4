// Built with Spec4 AI - https://spec4.ai
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { fetchReactRun } from '../../api/react'
import type { StoredRun } from './runAllowance'

/**
 * Traces from earlier runs this hour, re-fetched from the server on demand.
 *
 * **The stored record holds a run id, not a trace**, and this is where that
 * choice pays off: a restored trace is read back from
 * `GET /api/react/run/{run_id}`, which is the record the grounding audit was
 * computed against. A cached copy could drift from it and would then be showing
 * a visitor something no run actually produced — the same reasoning that keeps
 * the frontend from duplicating the preset catalogue.
 *
 * There is no server-side visitor identity, so without this a visitor who
 * looked at another example and came back would find their runs gone while the
 * counter had still been spent.
 */

/** Props for {@link PriorRuns}. */
export interface PriorRunsProps {
  runs: StoredRun[]
  /** The run currently on screen, which is not repeated here. */
  currentRunId: string | null
}

/**
 * List this hour's earlier runs, each expandable to its stored trace.
 *
 * @param props - The stored run records and the run already displayed.
 * @returns The prior-runs panel, or nothing when there are none to show.
 */
export function PriorRuns({ runs, currentRunId }: PriorRunsProps) {
  const earlier = runs.filter((run) => run.runId !== currentRunId)
  if (earlier.length === 0) {
    return null
  }

  return (
    <section
      data-testid="react-prior-runs"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        Earlier runs this hour
      </h3>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
        Re-read from the server by run id, so a restored trace is the
        authoritative record rather than a cached copy.
      </p>
      <ul className="mt-3 space-y-2">
        {earlier.map((run) => (
          <PriorRun key={run.runId} run={run} />
        ))}
      </ul>
    </section>
  )
}

function PriorRun({ run }: { run: StoredRun }) {
  const [open, setOpen] = useState(false)
  const trace = useQuery({
    queryKey: ['react', 'run', run.runId],
    queryFn: () => fetchReactRun(run.runId),
    enabled: open,
    staleTime: Infinity,
  })

  return (
    <li className="rounded-xl border border-gray-200 bg-gray-50 p-3 dark:border-gray-800 dark:bg-gray-950">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-2 text-left"
      >
        <span
          className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${
            run.ending === 'answer'
              ? 'border-emerald-400 text-emerald-700 dark:text-emerald-300'
              : 'border-amber-400 text-amber-700 dark:text-amber-300'
          }`}
        >
          {run.ending === 'answer' ? '✓ answered' : '⚠ budget exhausted'}
        </span>
        <span className="flex-1 text-xs text-gray-700 dark:text-gray-300">
          {run.question}
        </span>
        <span className="font-mono text-[10px] text-gray-500">
          {open ? 'hide' : 'show trace'}
        </span>
      </button>

      {open && trace.isPending && (
        <p className="mt-2 text-xs text-gray-500">Loading the stored trace…</p>
      )}
      {open && trace.isError && (
        <p className="mt-2 text-xs text-red-600 dark:text-red-400">
          That run&apos;s trace could not be read back.
        </p>
      )}
      {open && trace.data && (
        <ol className="mt-2 space-y-1.5" data-testid={`react-prior-trace-${run.runId}`}>
          {trace.data.cycle_trace.map((cycle) => (
            <li
              key={cycle.cycle}
              className="rounded-lg border border-gray-200 bg-white p-2 text-xs dark:border-gray-800 dark:bg-gray-900"
            >
              <span className="font-mono text-[10px] text-gray-500">
                cycle {cycle.cycle} · {cycle.action.kind}
              </span>
              <p className="mt-0.5 text-gray-700 dark:text-gray-300">{cycle.thought}</p>
              {cycle.action.query !== null && (
                <code className="mt-1 inline-block rounded border border-gray-300 bg-gray-50 px-1.5 py-0.5 font-mono text-[10px] dark:border-gray-700 dark:bg-gray-950">
                  {cycle.action.query}
                </code>
              )}
            </li>
          ))}
        </ol>
      )}
    </li>
  )
}

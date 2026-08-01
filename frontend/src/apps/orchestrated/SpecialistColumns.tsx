// Built with Spec4 AI - https://spec4.ai
import { Markdown } from '../../components/Markdown'
import type { Specialist } from '../../api/orchestrated'
import type { ColumnPhase, ColumnState } from './runState'

/**
 * The fan-out: two columns, each advancing on its own events.
 *
 * **Each column renders from its own entry in `state.columns` and nothing
 * gates one on the other.** That is not a stylistic choice — a single combined
 * state object would make both columns update together and destroy the visible
 * parallelism that is the entire point of the screen. `applyDispatchEvent`
 * returns the untouched column by reference precisely so this holds.
 *
 * There is **no typing animation**, though the design mock has one. The answer
 * arrives complete in a single SSE event, so a character-by-character reveal
 * would be inventing a stream the server did not send — the same theatre this
 * project removed from the tool-use screen and declined to add to chained
 * calls. What *is* real, and is shown, is that one column can finish while the
 * other is still working.
 *
 * A failed column stays on screen rather than disappearing: the visitor needs
 * to see which contribution is missing from the merge, not be quietly handed a
 * one-sided answer.
 */
export interface SpecialistColumnsProps {
  columns: ColumnState[]
  specialists: Specialist[]
}

const STATUS_LABEL: Record<ColumnPhase, string> = {
  waiting: 'queued',
  running: 'running',
  ok: 'complete',
  failed: 'failed',
  timeout: 'timed out',
}

const STATUS_CLASS: Record<ColumnPhase, string> = {
  waiting: 'text-gray-500 dark:text-gray-500',
  running: 'text-violet-600 dark:text-violet-400',
  ok: 'text-emerald-600 dark:text-emerald-400',
  failed: 'text-red-600 dark:text-red-400',
  timeout: 'text-amber-600 dark:text-amber-400',
}

/**
 * Render both specialist columns side by side.
 *
 * @param props - The per-column state and the roster for labels and colours.
 * @returns The fan-out panel.
 */
export function SpecialistColumns({ columns, specialists }: SpecialistColumnsProps) {
  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900">
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        Fan-out — both specialists run at the same time
      </h3>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-500">
        Neither depends on the other&rsquo;s output, so both were dispatched together. Each
        column is headed by the brief that specialist received.
      </p>

      {/* Stacks on small screens, side by side from `md`. */}
      <div className="mt-4 grid gap-4 md:grid-cols-2" data-testid="specialist-columns">
        {columns.map((column) => {
          const entry = specialists.find((item) => item.id === column.specialistId)
          return (
            <article
              key={column.specialistId}
              data-testid={`column-${column.specialistId}`}
              data-phase={column.phase}
              className="flex flex-col rounded-xl border border-gray-200 bg-gray-50 p-3 dark:border-gray-800 dark:bg-gray-950"
            >
              <header className="flex flex-wrap items-center justify-between gap-2">
                <p className="flex items-center gap-2 text-sm font-medium text-gray-900 dark:text-gray-100">
                  <span
                    aria-hidden="true"
                    className="h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: entry?.color ?? '#8b5cf6' }}
                  />
                  {entry?.displayName ?? column.specialistId}
                </p>
                <span
                  data-testid={`status-${column.specialistId}`}
                  className={
                    'flex items-center gap-1.5 font-mono text-xs ' + STATUS_CLASS[column.phase]
                  }
                >
                  {column.phase === 'running' ? (
                    <span
                      aria-hidden="true"
                      className="h-2.5 w-2.5 animate-spin rounded-full border-2 border-gray-300 border-t-violet-500 dark:border-gray-700"
                    />
                  ) : null}
                  {STATUS_LABEL[column.phase]}
                </span>
              </header>

              <div className="mt-2.5 rounded-lg border border-gray-200 bg-white p-2.5 dark:border-gray-800 dark:bg-gray-900">
                <p className="text-[10px] font-semibold tracking-wide text-gray-400 uppercase dark:text-gray-500">
                  Brief received
                </p>
                <p className="mt-1 text-xs leading-relaxed text-gray-600 dark:text-gray-400">
                  {column.instruction}
                </p>
              </div>

              <div className="mt-3 flex-1">
                {column.phase === 'ok' ? (
                  <>
                    <Markdown>{column.answer}</Markdown>
                    {column.keyPoints.length > 0 ? (
                      <ul className="mt-3 space-y-1 border-t border-gray-200 pt-3 dark:border-gray-800">
                        {column.keyPoints.map((point) => (
                          <li
                            key={point}
                            className="text-xs leading-relaxed text-gray-600 dark:text-gray-400"
                          >
                            • {point}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </>
                ) : null}

                {column.phase === 'failed' || column.phase === 'timeout' ? (
                  <p className="text-xs leading-relaxed text-red-600 dark:text-red-400">
                    {column.error ?? 'This specialist did not return an answer.'} Its column is
                    kept here so you can see which contribution is missing from the merge.
                  </p>
                ) : null}

                {column.phase === 'running' ? (
                  <p className="text-xs text-gray-500 dark:text-gray-500">
                    Working on its brief…
                  </p>
                ) : null}
              </div>
            </article>
          )
        })}
      </div>

      <p className="mt-3 text-[11px] text-gray-400 dark:text-gray-500">
        AI-generated demonstration output, not advice.
      </p>
    </section>
  )
}

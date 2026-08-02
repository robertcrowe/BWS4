// Built with Spec4 AI - https://spec4.ai
import { STAGE_LABELS, stageStatuses } from './runState'
import type { RunState } from './runState'

/**
 * The persistent 1–6 rail, so a six-stage flow stays followable.
 *
 * The capability names density as a likelihood-high failure mode: six stages,
 * two parallel tracks and a message log is a lot to hold at once. The rail is
 * the fix — one glance says where the run is.
 *
 * Its statuses are **derived from the events that arrived**, never from a
 * timer. A stage is done because the events after it exist.
 */

/** Props for {@link StageRail}. */
export interface StageRailProps {
  state: RunState
}

const DOT: Record<string, string> = {
  done: '✓',
  active: '●',
  failed: '×',
  pending: '○',
}

/**
 * Render the stage rail.
 *
 * @param props - The current run state.
 * @returns The rail.
 */
export function StageRail({ state }: StageRailProps) {
  const statuses = stageStatuses(state)

  return (
    <div data-testid="stage-rail" className="mb-4 flex flex-wrap gap-2">
      {STAGE_LABELS.map((label, index) => {
        const status = statuses[index]
        const tone =
          status === 'done'
            ? 'border-emerald-500/50 text-emerald-700 dark:text-emerald-400'
            : status === 'active'
              ? 'border-violet-500/60 text-violet-700 dark:text-violet-300'
              : status === 'failed'
                ? 'border-red-500/50 text-red-700 dark:text-red-400'
                : 'border-gray-200 text-gray-400 dark:border-gray-800 dark:text-gray-500'
        return (
          <span
            key={label}
            data-testid={`stage-${index + 1}`}
            data-status={status}
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 font-mono text-[11px] ${tone}`}
          >
            <span aria-hidden="true">{DOT[status]}</span>
            {index + 1}. {label}
          </span>
        )
      })}
    </div>
  )
}

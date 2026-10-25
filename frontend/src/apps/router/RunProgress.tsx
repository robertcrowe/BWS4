// Built with Spec4 AI - https://spec4.ai
import type { StageEvent } from '../../api/router'

/** Props for {@link RunProgress}. */
export interface RunProgressProps {
  stages: StageEvent[]
  /** True while the run is still streaming. */
  active: boolean
  /** Units the run holds; null until the server has admitted it. */
  unitsReserved: number | null
}

/**
 * The run's stages as they arrive: units held, then each step the server
 * reports. The last stage is the current one while the run is active.
 */
export function RunProgress({ stages, active, unitsReserved }: RunProgressProps) {
  return (
    <ul aria-label="Run progress" className="grid gap-1 text-sm">
      {unitsReserved === null ? (
        <li className="font-semibold text-indigo-700 dark:text-indigo-300">
          … Reserving model-call units
        </li>
      ) : (
        <li className="text-emerald-700 dark:text-emerald-400">
          ✓ Reserved {unitsReserved} model-call unit{unitsReserved === 1 ? '' : 's'}
        </li>
      )}
      {stages.map((stage, index) => {
        const current = active && index === stages.length - 1
        return (
          <li
            key={stage.stage}
            className={
              current
                ? 'font-semibold text-indigo-700 dark:text-indigo-300'
                : 'text-emerald-700 dark:text-emerald-400'
            }
          >
            {current ? '… ' : '✓ '}
            {stage.message}
          </li>
        )
      })}
    </ul>
  )
}

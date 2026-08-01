// Built with Spec4 AI - https://spec4.ai
import { useCallback, useState } from 'react'

import {
  RUN_CAP,
  readAllowance,
  readRuns,
  recordRun,
  runsRemaining,
  type RunAllowance,
  type StoredRun,
} from './runAllowance'

/**
 * React state over the advisory run counter and the stored run records.
 *
 * A custom hook rather than component state, per the project's convention, and
 * for a concrete reason: the counter and the prior runs are read from
 * `localStorage` **once, lazily, on mount**. That initial read is what
 * rehydrates a visitor who navigated away and came back — the count and the
 * answers they already have come back together, from one record, so they cannot
 * disagree about how many runs happened.
 *
 * Everything here is advisory. The hook offers no way to *refund* a run,
 * because a run is only ever recorded once it has finished; there is no window
 * in which a spent run needs giving back, and a refund path would be one more
 * thing to get wrong.
 */
export interface UseRunAllowance {
  allowance: RunAllowance
  /** Runs left in this UTC hour. */
  remaining: number
  /** True when this app's own limit is reached. */
  exhausted: boolean
  /** Runs already completed in this UTC hour, oldest first. */
  runs: StoredRun[]
  /** Record a finished run and spend one of the allowance. */
  complete: (run: StoredRun) => void
}

/**
 * Track the visitor's remaining runs and their completed runs this hour.
 *
 * @returns The allowance, the runs to re-render, and a way to record a new one.
 */
export function useRunAllowance(): UseRunAllowance {
  const [allowance, setAllowance] = useState<RunAllowance>(() => readAllowance())
  const [runs, setRuns] = useState<StoredRun[]>(() => readRuns())

  const complete = useCallback((run: StoredRun) => {
    setAllowance(recordRun(run))
    setRuns(readRuns())
  }, [])

  return {
    allowance,
    remaining: runsRemaining(allowance),
    exhausted: runsRemaining(allowance) === 0,
    runs,
    complete,
  }
}

export { RUN_CAP }

// Built with Spec4 AI - https://spec4.ai
import { useCallback, useState } from 'react'

import {
  readAllowance,
  readResults,
  recordRerun,
  recordResult,
  runsRemaining,
  type RunAllowance,
  type StoredRerun,
  type StoredResult,
} from './runAllowance'

/** What {@link useRunAllowance} returns. */
export interface UseRunAllowance {
  allowance: RunAllowance
  /** Runs left this visit. */
  remaining: number
  /** True when this app's own 5-run limit is reached. */
  exhausted: boolean
  /** Results completed this visit, oldest first. */
  results: StoredResult[]
  /** Record a finished run and spend one of the allowance. */
  complete: (result: StoredResult) => void
  /** Record a finished re-run beside its original and spend one run. */
  completeRerun: (originalRunId: string, rerun: StoredRerun) => void
}

/**
 * React state over the advisory five-run counter and the stored results.
 *
 * Read from `localStorage` once, lazily, on mount, so a visitor who navigates
 * away and back gets their count and their results back together. There is no
 * refund: a run is recorded only once it has ended.
 *
 * @returns The allowance, the stored results, and a way to record a new one.
 */
export function useRunAllowance(): UseRunAllowance {
  const [allowance, setAllowance] = useState<RunAllowance>(() => readAllowance())
  const [results, setResults] = useState<StoredResult[]>(() => readResults())

  const complete = useCallback((result: StoredResult) => {
    setAllowance(recordResult(result))
    setResults(readResults())
  }, [])

  const completeRerun = useCallback((originalRunId: string, rerun: StoredRerun) => {
    setAllowance(recordRerun(originalRunId, rerun))
    setResults(readResults())
  }, [])

  return {
    allowance,
    remaining: runsRemaining(allowance),
    exhausted: runsRemaining(allowance) === 0,
    results,
    complete,
    completeRerun,
  }
}

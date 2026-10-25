// Built with Spec4 AI - https://spec4.ai
/**
 * The advisory five-run counter, and the results of the runs already made.
 *
 * **This is not quota protection and the UI must never present it as such.** It
 * lives in `localStorage`, so anyone can clear it. The real limit is
 * server-side: two units held against the shared hourly cap before the router
 * runs. What this counter is for is the teaching point — a visitor watches a
 * budget being spent rather than discovering one by hitting it.
 *
 * **It resets on the UTC hour**, mirroring the server's window, and a run is
 * spent only from the `run_end` event: a refused run never began, so it costs
 * nothing, and there is no refund path to get wrong.
 *
 * Unlike the ReAct counter it keeps each run's whole result — the decision
 * card, the answer and the unit accounting. A Router result is small, and the
 * server keeps no per-run record to re-fetch, so this is the only way earlier
 * results can stay on screen after navigation.
 */
import type { AnswerEvent, DecisionEvent, RunEndEvent } from '../../api/router'

/** Runs a visitor may complete per visit (per UTC hour). */
export const RUN_CAP = 5

/** {@link RUN_CAP} under a name that reads clearly outside this module. */
export const ROUTER_RUN_CAP = RUN_CAP

/** Storage key, distinct from every other app's. */
export const STORAGE_KEY = 'router_run_allowance'

/**
 * Shown when *this app's* 5-run limit is reached. Never merged with the shared
 * cap message: different limits, different owners, different remedies.
 */
export const SESSION_LIMIT_MESSAGE =
  "You've used all 5 Router runs for this visit. That's this app's own 5-run " +
  "limit — not the showcase's shared cap, which may well have room left. Your " +
  'earlier results stay on screen, and the counter resets at the top of the hour.'

/** A completed comparison re-run, kept beside the run it re-ran. */
export interface StoredRerun {
  answer: AnswerEvent | null
  end: RunEndEvent
}

/** One completed run, kept so its card stays on screen. */
export interface StoredResult {
  runId: string
  request: string
  presetId: string | null
  decision: DecisionEvent
  /** Null only for a result stored before answers existed. */
  answer: AnswerEvent | null
  end: RunEndEvent
  /** The run's one comparison re-run, once made. */
  rerun?: StoredRerun | null
}

export interface RunAllowance {
  used: number
  cap: number
}

interface StoredRecord extends RunAllowance {
  /** The UTC hour this record belongs to, as YYYY-MM-DDTHH. */
  window: string
  results: StoredResult[]
}

const EMPTY: RunAllowance = { used: 0, cap: RUN_CAP }

/**
 * The current UTC hour, as the backend computes its window.
 *
 * @param now - Injectable clock.
 * @returns The window key, YYYY-MM-DDTHH.
 */
export function utcWindow(now: Date = new Date()): string {
  return now.toISOString().slice(0, 13)
}

function readRecord(now: Date): StoredRecord | null {
  let raw: string | null = null
  try {
    raw = window.localStorage.getItem(STORAGE_KEY)
  } catch {
    // Private-mode Safari throws here. Advisory only: degrade the display.
    return null
  }
  if (!raw) {
    return null
  }
  try {
    const stored = JSON.parse(raw) as Partial<StoredRecord>
    if (typeof stored.used !== 'number' || stored.window !== utcWindow(now)) {
      return null
    }
    return {
      used: Math.max(0, Math.min(stored.used, RUN_CAP)),
      cap: RUN_CAP,
      window: stored.window,
      results: Array.isArray(stored.results) ? stored.results : [],
    }
  } catch {
    // A corrupted key should cost a visitor their counter, never the screen.
    return null
  }
}

function write(record: StoredRecord): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(record))
  } catch {
    // Storage unavailable. Advisory only.
  }
}

/**
 * Read the current allowance, rolling over on a new UTC hour.
 *
 * @param now - Injectable clock.
 * @returns The allowance.
 */
export function readAllowance(now: Date = new Date()): RunAllowance {
  const record = readRecord(now)
  return record ? { used: record.used, cap: record.cap } : EMPTY
}

/**
 * Read the results completed this UTC hour, oldest first.
 *
 * @param now - Injectable clock.
 * @returns The stored results.
 */
export function readResults(now: Date = new Date()): StoredResult[] {
  return readRecord(now)?.results ?? []
}

/**
 * Runs left this hour.
 *
 * @param allowance - The current allowance.
 * @returns Runs remaining, never negative.
 */
export function runsRemaining(allowance: RunAllowance): number {
  return Math.max(0, allowance.cap - allowance.used)
}

/**
 * Record a finished run and spend one of the allowance.
 *
 * @param result - The finished run.
 * @param now - Injectable clock.
 * @returns The allowance after spending one run.
 */
export function recordResult(result: StoredResult, now: Date = new Date()): RunAllowance {
  const current = readRecord(now)
  const next: StoredRecord = {
    used: Math.min((current?.used ?? 0) + 1, RUN_CAP),
    cap: RUN_CAP,
    window: utcWindow(now),
    results: [...(current?.results ?? []), result].slice(-RUN_CAP),
  }
  write(next)
  return { used: next.used, cap: next.cap }
}

/**
 * Record a finished comparison re-run beside the run it re-ran, and spend one
 * of the allowance — a re-run counts as one of the five.
 *
 * @param originalRunId - The run that was re-run.
 * @param result - The re-run's answer and ending.
 * @param now - Injectable clock.
 * @returns The allowance after spending one run.
 */
export function recordRerun(
  originalRunId: string,
  result: StoredRerun,
  now: Date = new Date(),
): RunAllowance {
  const current = readRecord(now)
  const next: StoredRecord = {
    used: Math.min((current?.used ?? 0) + 1, RUN_CAP),
    cap: RUN_CAP,
    window: utcWindow(now),
    results: (current?.results ?? []).map((stored) =>
      stored.runId === originalRunId ? { ...stored, rerun: result } : stored,
    ),
  }
  write(next)
  return { used: next.used, cap: next.cap }
}

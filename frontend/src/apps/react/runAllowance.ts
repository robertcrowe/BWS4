// Built with Spec4 AI - https://spec4.ai
/**
 * The advisory two-run counter, and the record of runs already made.
 *
 * **This is not quota protection and the UI must never present it as such.** It
 * lives in `localStorage`, so anyone can clear it in a second. The real limits
 * are server-side and unreachable from here: a per-UTC-hour cap on generation,
 * a ten-request ceiling per run, and an allowance hold taken before the first
 * cycle. What this counter is *for* is the teaching point — a visitor should
 * watch a budget being spent rather than discover one by hitting it.
 *
 * **Two runs, the gallery's tightest per-app limit**, because this is the only
 * example that can issue a search on every cycle.
 *
 * **It resets on the UTC hour, mirroring `usage_limits.window_start`.** The
 * server rolls its window the same way and at the same instant; a counter that
 * only incremented would make the on-screen reset copy false and would strand a
 * visitor whose browser remembered two runs from last week.
 *
 * **Only the run id and the question are stored, never the trace.** That is the
 * one deliberate difference from `apps/orchestrated/runAllowance.ts`, which
 * keeps its whole result. A ReAct trace is large — up to eight observations of
 * five snippets each — and the server already holds the authoritative copy, so
 * a restored run is re-fetched from `GET /api/react/run/{run_id}` rather than
 * trusted from cache. Caching the trace would mean a stale copy could disagree
 * with the record the audit was computed against.
 */

/** Runs a visitor may complete per UTC hour before the advisory limit is reached. */
export const RUN_CAP = 2

/**
 * Storage key, distinct from every other app's.
 *
 * Named rather than inlined because three apps now keep an hourly counter, and
 * a shared key would let one app's runs silently spend another's.
 */
export const STORAGE_KEY = 'react_run_allowance'

/**
 * Shown when *this app's* two-run session limit is reached.
 *
 * Kept as a separate constant from the showcase-wide message below, and they
 * must never be merged. They describe different limits with different owners
 * and different remedies: this one is per-device and resets on the hour; the
 * other is shared by every example app and is the operator's. A single "limit
 * reached" string would leave a visitor unable to tell which they hit, and the
 * capability requires the two be distinguishable.
 */
export const SESSION_LIMIT_MESSAGE =
  "You've used both ReAct runs allowed for this example in this hour. That's " +
  "this demo's own limit — the gallery's tightest, because a loop can issue a " +
  'search on every cycle — and not the showcase-wide allowance, which may well ' +
  'have plenty left. Your previous traces stay on screen, and the counter ' +
  'resets at the top of the hour.'

/** Shown when the *showcase-wide* hourly allowance refuses the run. */
export const SHOWCASE_LIMIT_MESSAGE =
  'The showcase-wide hourly allowance, shared by every example app, is ' +
  "exhausted. That's not this demo's own two-run limit — nothing was searched " +
  'and no model was called, because a run reserves its whole budget before it ' +
  'starts. It resets at the top of the hour.'

/** One completed run, kept so its trace can be re-fetched after navigation. */
export interface StoredRun {
  runId: string
  question: string
  /** How the run ended, for the summary line shown before the trace loads. */
  ending: 'answer' | 'exhausted'
}

export interface RunAllowance {
  used: number
  cap: number
}

interface StoredRecord extends RunAllowance {
  /** The UTC hour this record belongs to, as YYYY-MM-DDTHH. */
  window: string
  runs: StoredRun[]
}

const EMPTY: RunAllowance = { used: 0, cap: RUN_CAP }

/**
 * The current UTC hour, matching how the backend computes its window.
 *
 * Sliced from the ISO string rather than assembled from parts so it cannot
 * disagree with itself about padding, month offsets, or the local timezone —
 * local time would drift out of step with the server by up to a day at the
 * date line.
 *
 * @param now - Injectable clock, so the rollover is testable.
 * @returns The window key, as YYYY-MM-DDTHH.
 */
export function utcWindow(now: Date = new Date()): string {
  return now.toISOString().slice(0, 13)
}

function readRecord(now: Date): StoredRecord | null {
  let raw: string | null = null
  try {
    raw = window.localStorage.getItem(STORAGE_KEY)
  } catch {
    // `localStorage` itself throws in Safari's private mode. The counter is
    // advisory, so losing it degrades the display and nothing else.
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
      runs: Array.isArray(stored.runs) ? stored.runs : [],
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
    // Storage unavailable. Advisory only — the server's limits are untouched.
  }
}

/**
 * Read the current allowance, rolling the counter over on a new UTC hour.
 *
 * @param now - Injectable clock, so the rollover is testable.
 * @returns The allowance to display and check against.
 */
export function readAllowance(now: Date = new Date()): RunAllowance {
  const record = readRecord(now)
  return record ? { used: record.used, cap: record.cap } : EMPTY
}

/**
 * Read the runs completed in the current UTC hour.
 *
 * Returns nothing for a stale record: the counter and the run records roll over
 * together, so a visitor is never shown two traces beside a counter reading
 * "2 runs remaining".
 *
 * @param now - Injectable clock.
 * @returns Completed runs, oldest first.
 */
export function readRuns(now: Date = new Date()): StoredRun[] {
  return readRecord(now)?.runs ?? []
}

/**
 * Runs left this hour.
 *
 * @param allowance - The current allowance.
 * @returns How many runs remain, never negative.
 */
export function runsRemaining(allowance: RunAllowance): number {
  return Math.max(0, allowance.cap - allowance.used)
}

/**
 * Record a completed run and spend one of the allowance.
 *
 * Called when a run **finishes**, not when it is started — so the counter and
 * the stored record are written in one step and cannot disagree about how many
 * runs there were, and there is no refund path to get wrong.
 *
 * @param run - The finished run to remember.
 * @param now - Injectable clock.
 * @returns The allowance after spending one run.
 */
export function recordRun(run: StoredRun, now: Date = new Date()): RunAllowance {
  const current = readRecord(now)
  const next: StoredRecord = {
    used: Math.min((current?.used ?? 0) + 1, RUN_CAP),
    cap: RUN_CAP,
    window: utcWindow(now),
    runs: [...(current?.runs ?? []), run].slice(-RUN_CAP),
  }
  write(next)
  return { used: next.used, cap: next.cap }
}

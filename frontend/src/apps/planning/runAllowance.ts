// Built with Spec4 AI - https://spec4.ai
/**
 * The advisory per-visitor run counter.
 *
 * **This is not quota protection and must never be described as such.** It
 * lives in `localStorage`, so anyone can clear it in a second. The real limits
 * are server-side and unreachable from here: a per-UTC-hour cap on planning
 * runs, a per-UTC-hour cap on generation and search, and a hard per-run
 * model-call ceiling. What this counter is *for* is the teaching point — a planning agent
 * is unbounded by nature, and a visitor should see a budget being spent rather
 * than discover one by hitting it.
 *
 * **It resets on the UTC hour, deliberately mirroring `usage_limits.window_start`.**
 * A counter that only ever incremented would make the UI's stated reset a lie on
 * the one screen where the reset is the thing being explained — and would strand
 * a visitor whose browser remembers three runs from last week. The server rolls
 * its window the same way and at the same instant, which is the whole reason to
 * track the window here rather than just a count. It followed the server from
 * daily to hourly in v5; if the server's window ever moves again, this moves
 * with it.
 *
 * Pure module beside the components, so it is testable without rendering and
 * stays off React's fast-refresh path — the same arrangement as
 * `apps/chained-calls/chainState.ts`.
 */

/** Runs a visitor may start per UTC hour before the advisory limit is reached. */
export const RUN_CAP = 3

const STORAGE_KEY = 'planning_run_allowance'

export interface RunAllowance {
  used: number
  cap: number
}

interface StoredAllowance extends RunAllowance {
  /** The UTC hour the counter belongs to, as YYYY-MM-DDTHH. */
  window: string
}

/**
 * The current UTC hour, matching how the backend computes its window.
 *
 * Sliced from the ISO string rather than assembled from parts so it cannot
 * disagree with itself about padding or month offsets.
 *
 * @param now - Injectable clock, so the rollover is testable.
 * @returns The window key, as YYYY-MM-DDTHH.
 */
export function utcWindow(now: Date = new Date()): string {
  return now.toISOString().slice(0, 13)
}

const EMPTY: RunAllowance = { used: 0, cap: RUN_CAP }

/**
 * Read the current allowance, rolling the counter over on a new UTC day.
 *
 * Tolerates absent, unparseable and malformed storage by returning a fresh
 * allowance: a corrupted key should cost a visitor their counter, never the
 * screen. `localStorage` itself can throw — Safari's private mode does — so
 * even the read is guarded.
 *
 * @param now - Injectable clock, so the rollover is testable.
 * @returns The allowance to display and check against.
 */
export function readAllowance(now: Date = new Date()): RunAllowance {
  let raw: string | null = null
  try {
    raw = window.localStorage.getItem(STORAGE_KEY)
  } catch {
    return EMPTY
  }
  if (!raw) {
    return EMPTY
  }

  try {
    const stored = JSON.parse(raw) as Partial<StoredAllowance>
    if (typeof stored.used !== 'number' || stored.window !== utcWindow(now)) {
      return EMPTY
    }
    return { used: Math.max(0, Math.min(stored.used, RUN_CAP)), cap: RUN_CAP }
  } catch {
    return EMPTY
  }
}

/**
 * Record that a run has started.
 *
 * Called when execution begins, not when a plan is generated. The capability is
 * explicit that a run which never executed a step costs nothing — so a visitor
 * who reviews a plan and walks away keeps their allowance, and there is no
 * refund path to get wrong.
 *
 * @param now - Injectable clock.
 * @returns The allowance after spending one run.
 */
export function spendRun(now: Date = new Date()): RunAllowance {
  const current = readAllowance(now)
  const next: StoredAllowance = {
    used: Math.min(current.used + 1, RUN_CAP),
    cap: RUN_CAP,
    window: utcWindow(now),
  }

  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    // Storage unavailable. The counter is advisory, so losing it degrades the
    // display and nothing else — the server's limits are untouched.
  }

  return { used: next.used, cap: next.cap }
}

/** Runs left before the advisory limit is reached. */
export function runsRemaining(allowance: RunAllowance): number {
  return Math.max(0, allowance.cap - allowance.used)
}

/** Whether the advisory limit has been reached. */
export function isExhausted(allowance: RunAllowance): boolean {
  return runsRemaining(allowance) === 0
}

// Built with Spec4 AI - https://spec4.ai
/**
 * The advisory per-visitor run counter, and the record of runs already made.
 *
 * **This is not quota protection and the UI must never present it as such.** It
 * lives in `localStorage`, so anyone can clear it in a second. The real limits
 * are server-side and unreachable from here: a per-UTC-hour cap on generation,
 * a four-request ceiling per run, and an allowance hold taken before the
 * coordinator is even called. What this counter is *for* is the teaching point
 * — a visitor should watch a budget being spent rather than discover one by
 * hitting it.
 *
 * **It resets on the UTC hour, mirroring `usage_limits.window_start`.** The
 * server rolls its window the same way and at the same instant; a counter that
 * only incremented would make the on-screen reset copy false and would strand a
 * visitor whose browser remembered three runs from last week. Deriving the
 * stamp from `toISOString()` rather than local-time parts is deliberate — local
 * time would drift out of step with the server by up to a day at the date line.
 *
 * **Completed runs are stored beside the counter, and that is what makes the
 * screen survive navigation.** There is no server-side visitor identity, no
 * session cookie and no run store, so if this record did not exist a visitor
 * returning to the page would find their answers gone while their counter had
 * still been spent. Storing them here is the only way to make the count and the
 * results agree.
 *
 * A pure module beside the components, so it is testable without rendering and
 * stays off React's fast-refresh path — the same arrangement as
 * `apps/planning/runAllowance.ts`, whose conventions this follows.
 */
import type {
  DelegationDecision,
  MergedAnswerEvent,
  SpecialistAnswerEvent,
} from '../../api/orchestrated'

/** Runs a visitor may complete per UTC hour before the advisory limit is reached. */
export const RUN_CAP = 3

/**
 * Storage key, distinct from `planning_run_allowance` and `theme_preference`.
 *
 * Named rather than inlined because two apps now keep an hourly counter, and a
 * shared key would let one app's runs silently spend the other's.
 */
export const STORAGE_KEY = 'orchestrated_run_allowance'

/**
 * Shown when *this app's* session limit is reached.
 *
 * Kept as a separate constant from the showcase-wide message below, and they
 * must never be merged. They describe different limits with different owners
 * and different remedies: this one is per-device and resets on the hour; the
 * other is shared by every example app and is the operator's. A single "limit
 * reached" string would leave a visitor unable to tell which, and the
 * capability requires the two be distinguishable.
 */
export const SESSION_LIMIT_MESSAGE =
  "You've used all 3 orchestration runs for this example in this hour. That's " +
  "this demo's own limit, not the showcase-wide allowance — the shared " +
  'generation capability may still have plenty left. Your previous results stay ' +
  'on screen, and the counter resets at the top of the hour.'

/** Shown when the *showcase-wide* hourly allowance refuses the run. */
export const SHOWCASE_LIMIT_MESSAGE =
  'The showcase-wide hourly allowance, shared by every example app, is ' +
  "exhausted. That's not this demo's own 3-run limit — nothing was dispatched, " +
  'because a run reserves its whole budget before it starts. It resets at the ' +
  'top of the hour.'

/** One specialist column as it was when the run finished. */
export interface StoredColumn {
  specialistId: string
  instruction: string
  status: SpecialistAnswerEvent['status']
  answer: string
  keyPoints: string[]
  error: string | null
}

/** One completed run, kept so it can be shown again after navigation. */
export interface StoredRun {
  question: string
  decision: DelegationDecision
  columns: StoredColumn[]
  merged: MergedAnswerEvent | null
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
 * disagree with itself about padding, month offsets, or the local timezone.
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
 * Returns nothing for a stale record: the counter and the results roll over
 * together, so a visitor is never shown three answers beside a counter reading
 * "3 runs remaining".
 *
 * @param now - Injectable clock.
 * @returns Completed runs, oldest first.
 */
export function readRuns(now: Date = new Date()): StoredRun[] {
  return readRecord(now)?.runs ?? []
}

/**
 * Record a completed run and spend one of the allowance.
 *
 * Called when a run **finishes**, not when it is dispatched — so the counter
 * and the stored results are written in one step and cannot disagree about how
 * many runs there were.
 *
 * @param run - The finished run to keep.
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

/** Runs left before the advisory limit is reached. */
export function runsRemaining(allowance: RunAllowance): number {
  return Math.max(0, allowance.cap - allowance.used)
}

/** Whether the advisory limit has been reached. */
export function isExhausted(allowance: RunAllowance): boolean {
  return runsRemaining(allowance) === 0
}

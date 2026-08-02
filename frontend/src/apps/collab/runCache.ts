// Built with Spec4 AI - https://spec4.ai
/**
 * Keeps the visitor's most recent completed run, so returning rehydrates it.
 *
 * There is no server-side visitor identity here — no account, no session
 * cookie, no per-visitor run store. Without this, someone who navigates to
 * another example and comes back finds their negotiation gone: six stages of
 * waiting, an award, an unsealing, and nothing to show for it. The record is
 * kept locally so the page can restore itself with **no network call at all**.
 *
 * ## Layered over the database, not replacing it
 *
 * `negotiation_runs` and `peer_messages` remain authoritative — this is a
 * convenience for one browser. Nothing here is trusted for anything that
 * matters: it is never sent back to the server, never used to skip a check,
 * and never counted against an allowance.
 *
 * ## No per-app session counter, deliberately
 *
 * This app's run limit is the framework-standard hourly `usage_limits` gate,
 * which the server enforces. The orchestrated and planning apps keep a local
 * counter because their capabilities specify a per-app one; the stack spec is
 * explicit that this app has none. Adding a client-side counter here would
 * invent a limit the backend does not apply, and a limit the visitor could
 * clear by opening a private window is not a limit anyway.
 */
import type { RunState } from './runState'

/** Distinct from `planning_run_allowance` and `orchestrated_run_allowance`. */
export const STORAGE_KEY = 'collab_last_run'

/** Bumped when the stored shape changes, so an old entry is dropped rather than misread. */
const CACHE_VERSION = 1

/** What is kept between visits. */
export interface CachedRun {
  version: number
  scenarioId: string
  weightingId: string
  /** The fields of `RunState` worth restoring. Transient phases are not among them. */
  state: Pick<
    RunState,
    | 'sellerOrder'
    | 'columns'
    | 'requestText'
    | 'declaredBudget'
    | 'counterOffers'
    | 'award'
    | 'awardReconciled'
    | 'reconciliationNote'
    | 'messages'
    | 'sellerToSellerCount'
    | 'reveal'
    | 'sensitivity'
  >
}

function storage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    // Private browsing and blocked-storage settings both throw on access. A
    // cache is a convenience, so losing it must never break the page.
    return null
  }
}

/**
 * Store a completed run.
 *
 * Called once, when the run finishes — not per event. A partially written run
 * restored on a later visit would show a half-finished negotiation with no way
 * to tell it was interrupted.
 *
 * @param state - The finished run state.
 * @param scenarioId - The scenario that was negotiated.
 * @param weightingId - The weighting that was applied.
 */
export function saveRun(state: RunState, scenarioId: string, weightingId: string): void {
  const store = storage()
  if (!store) {
    return
  }
  const cached: CachedRun = {
    version: CACHE_VERSION,
    scenarioId,
    weightingId,
    state: {
      sellerOrder: state.sellerOrder,
      columns: state.columns,
      requestText: state.requestText,
      declaredBudget: state.declaredBudget,
      counterOffers: state.counterOffers,
      award: state.award,
      awardReconciled: state.awardReconciled,
      reconciliationNote: state.reconciliationNote,
      messages: state.messages,
      sellerToSellerCount: state.sellerToSellerCount,
      reveal: state.reveal,
      sensitivity: state.sensitivity,
    },
  }
  try {
    store.setItem(STORAGE_KEY, JSON.stringify(cached))
  } catch {
    // A full quota is not worth failing a completed run over.
  }
}

/**
 * Read back the most recent completed run.
 *
 * @returns The cached run, or null when there is none, it is unreadable, or it
 * was written by an older version of this shape.
 */
export function loadRun(): CachedRun | null {
  const store = storage()
  if (!store) {
    return null
  }
  const raw = store.getItem(STORAGE_KEY)
  if (!raw) {
    return null
  }
  try {
    const parsed = JSON.parse(raw) as CachedRun
    // A stale shape is dropped rather than partially read: half-restoring a
    // run is worse than not restoring one.
    return parsed.version === CACHE_VERSION ? parsed : null
  } catch {
    return null
  }
}

/** Forget the stored run. */
export function clearRun(): void {
  storage()?.removeItem(STORAGE_KEY)
}

/**
 * Rebuild a `RunState` from a cached run.
 *
 * The restored run is marked `complete` — it is, by construction, since only
 * finished runs are cached.
 *
 * @param cached - The stored run.
 * @param initial - A fresh empty state to layer over.
 * @returns The rehydrated state.
 */
export function rehydrate(cached: CachedRun, initial: RunState): RunState {
  return { ...initial, ...cached.state, phase: 'complete' }
}

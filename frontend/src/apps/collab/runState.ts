// Built with Spec4 AI - https://spec4.ai
/**
 * Folds the negotiation stream into one slice of state per seller.
 *
 * A pure module beside the components, the arrangement `planState.ts`,
 * `orchestrated/runState.ts` and `plotTraces.ts` already use here.
 *
 * ## The two sellers are two independent slices, and that is the whole point
 *
 * `applyRunEvent` returns the untouched seller's slice **by reference**. A
 * single combined object updated on every event would make both columns move
 * together, and the visible fan-out — the thing this screen teaches — would
 * disappear even though the backend really did run them concurrently. A test
 * that only checked "both bids eventually appear" cannot tell the two
 * implementations apart; `leaves the other column in progress` can.
 *
 * ## Every state is derived from an event that arrived
 *
 * Never from a timer. This project has removed invented progress three times —
 * the tool-use step animation, the chained-calls hand-off, and the mock's
 * typing effect — and this is the surface where faking it would be easiest:
 * "two columns both working" is exactly what a `setTimeout` counterfeits well.
 * A column is bidding because the server said the round started, and it is done
 * because the server sent its bid.
 *
 * ## One named state per condition
 *
 * The phase's fourth risk is an incomplete state machine rendering blank
 * panels: six stages, two tracks, degraded, halted, unreconciled, cap-refused.
 * `RunPhase` and `ColumnPhase` name every one, so nothing falls through.
 */
import type {
  AwardEvent,
  CounterOfferEvent,
  DeclaredBudget,
  PeerMessageRow,
  RevealPayload,
  RunEvent,
  SensitivityPayload,
} from '../../api/collab'

/** How the run as a whole is doing. */
export type RunPhase =
  | 'idle'
  /** Requested, but no event has arrived yet. Render this, don't render blank —
   *  Render's free tier spins down, so a cold start before the first event is a
   *  routine path rather than an edge case. */
  | 'connecting'
  | 'running'
  | 'complete'
  /** Stopped partway with results worth keeping on screen. */
  | 'halted'
  /** Refused before stage 1 by the shared hourly allowance. */
  | 'cap_refused'
  /** The transport failed, which is a different problem from a cap. */
  | 'unreachable'

/** How one seller's column is doing. */
export type ColumnPhase = 'waiting' | 'bidding' | 'opening_in' | 'final_in' | 'failed'

/** One seller's bid at one round. */
export interface ColumnBid {
  unitPrice: number
  quantity: number
  deliveryDays: number
  warrantyMonths: number
  notes: string
  concessions: string[]
  reissued: boolean
}

/** One seller's column. */
export interface ColumnState {
  sellerId: string
  phase: ColumnPhase
  opening: ColumnBid | null
  final: ColumnBid | null
  counter: CounterOfferEvent | null
  /** Visitor-readable explanation, present only when the column failed. */
  error: string | null
}

/** A refusal or failure the whole run stopped on. */
export interface RunError {
  code: string
  message: string
  /** Present only on a cap refusal — the two must stay distinguishable. */
  allowance: { remaining: number; cap: number; resetsAt: string } | null
}

/** Everything the stream has said so far. */
export interface RunState {
  phase: RunPhase
  /** Seller ids in the order the server listed them, so columns never reorder. */
  sellerOrder: string[]
  columns: Record<string, ColumnState>
  requestText: string
  declaredBudget: DeclaredBudget | null
  counterOffers: CounterOfferEvent[]
  award: AwardEvent | null
  /** False when the award did not follow from its own scoring. */
  awardReconciled: boolean
  reconciliationNote: string
  messages: PeerMessageRow[]
  sellerToSellerCount: number | null
  /**
   * The post-award unsealing. Null until the award lands, and that is not a
   * loading state — it is the opacity claim: there is nothing to reveal until
   * the round has concluded, and the server will not produce it earlier.
   */
  reveal: RevealPayload | null
  sensitivity: SensitivityPayload | null
  error: RunError | null
}

/** The declared cost shown before a run starts, and while one is in flight. */
export const DECLARED_BUDGET: DeclaredBudget = {
  total: 8,
  negotiation: 6,
  explanation: 2,
}

/**
 * Build the empty starting state.
 *
 * @returns A run that has not been requested yet.
 */
export function initialRunState(): RunState {
  return {
    phase: 'idle',
    sellerOrder: [],
    columns: {},
    requestText: '',
    declaredBudget: null,
    counterOffers: [],
    award: null,
    awardReconciled: true,
    reconciliationNote: '',
    messages: [],
    sellerToSellerCount: null,
    reveal: null,
    sensitivity: null,
    error: null,
  }
}

function emptyColumn(sellerId: string): ColumnState {
  return {
    sellerId,
    phase: 'bidding',
    opening: null,
    final: null,
    counter: null,
    error: null,
  }
}

function toBid(event: Extract<RunEvent, { kind: 'bid' }>): ColumnBid {
  return {
    unitPrice: event.unit_price,
    quantity: event.quantity,
    deliveryDays: event.delivery_days,
    warrantyMonths: event.warranty_months,
    notes: event.notes,
    concessions: event.concessions_made ?? [],
    reissued: event.reissued === true,
  }
}

/**
 * Apply one stage event to the run state.
 *
 * Pure: returns a new state and mutates nothing. The seller not named by an
 * event keeps its **existing object identity**, which is what makes one
 * column's progress independent of the other's rather than merely eventual.
 *
 * @param state - The state before this event.
 * @param event - The event that arrived.
 * @returns The state after it.
 */
export function applyRunEvent(state: RunState, event: RunEvent): RunState {
  switch (event.kind) {
    case 'quotation_request': {
      const columns: Record<string, ColumnState> = {}
      for (const sellerId of event.sellers) {
        columns[sellerId] = emptyColumn(sellerId)
      }
      return {
        ...state,
        phase: 'running',
        sellerOrder: event.sellers,
        columns,
        requestText: event.request.text,
        declaredBudget: event.declared_budget,
      }
    }

    case 'bid': {
      const existing = state.columns[event.seller_id]
      if (!existing) {
        return state
      }
      const isOpening = event.stage === 'opening_bids'
      // Only this seller's slice is rebuilt. Every other entry in `columns` is
      // carried over by reference, unchanged.
      return {
        ...state,
        columns: {
          ...state.columns,
          [event.seller_id]: {
            ...existing,
            phase: isOpening ? 'opening_in' : 'final_in',
            opening: isOpening ? toBid(event) : existing.opening,
            final: isOpening ? existing.final : toBid(event),
          },
        },
      }
    }

    case 'counter_offers': {
      const columns = { ...state.columns }
      for (const offer of event.offers) {
        const existing = columns[offer.seller_id]
        if (existing) {
          columns[offer.seller_id] = { ...existing, counter: offer, phase: 'bidding' }
        }
      }
      return { ...state, counterOffers: event.offers, columns }
    }

    case 'degraded': {
      const existing = state.columns[event.seller_id]
      if (!existing) {
        return state
      }
      return {
        ...state,
        columns: {
          ...state.columns,
          [event.seller_id]: {
            ...existing,
            phase: 'failed',
            error:
              event.status === 'timed_out'
                ? 'This supplier did not answer in time, so its track stops here. The other supplier’s bid is unaffected.'
                : 'This supplier could not be reached, so its track stops here. The other supplier’s bid is unaffected.',
          },
        },
      }
    }

    case 'award':
      return {
        ...state,
        award: event.award,
        awardReconciled: event.reconciled,
        reconciliationNote: event.reconciliation_note,
      }

    case 'reveal': {
      const { kind: _kind, stage: _stage, ...payload } = event
      return { ...state, reveal: payload }
    }

    case 'sensitivity': {
      const { kind: _kind, stage: _stage, ...payload } = event
      return { ...state, sensitivity: payload }
    }

    case 'message_log':
      return {
        ...state,
        phase: state.error ? state.phase : 'complete',
        messages: event.messages,
        sellerToSellerCount: event.seller_to_seller_count,
      }

    case 'error': {
      const isCap = event.outcome === 'usage_limit_reached'
      return {
        ...state,
        // A run that produced stages and then stopped is `halted`, not
        // `cap_refused`: the capability requires results already on screen stay
        // there, and the two need different copy.
        phase: isCap ? 'cap_refused' : 'halted',
        error: {
          code: event.code,
          message: event.message,
          allowance:
            isCap && event.remaining !== undefined
              ? {
                  remaining: event.remaining,
                  cap: event.cap ?? 0,
                  resetsAt: event.resets_at ?? '',
                }
              : null,
        },
      }
    }

    case 'routing':
      return state

    default:
      return state
  }
}

/** The six stages, in the order the backend advances them. */
export const STAGE_LABELS = [
  'RFQ composed',
  'Opening bids',
  'Counter-offers',
  'Counter delivery',
  'Best & final',
  'Award',
] as const

/** How far the stage rail has got. */
export type StageStatus = 'pending' | 'active' | 'done' | 'failed'

/**
 * Derive each stage's status from what has arrived.
 *
 * Derived, never timed — see this module's docstring. A stage is done because
 * the events that follow it exist, not because a duration elapsed.
 *
 * @param state - The current run state.
 * @returns One status per stage, in `STAGE_LABELS` order.
 */
export function stageStatuses(state: RunState): StageStatus[] {
  if (state.phase === 'idle' || state.phase === 'cap_refused') {
    return STAGE_LABELS.map(() => 'pending')
  }

  const columns = Object.values(state.columns)
  const done = [
    state.requestText !== '',
    columns.length > 0 && columns.every((c) => c.opening !== null || c.phase === 'failed'),
    state.counterOffers.length > 0,
    state.counterOffers.length > 0,
    columns.length > 0 && columns.every((c) => c.final !== null || c.phase === 'failed'),
    state.award !== null,
  ]

  const firstPending = done.indexOf(false)
  return STAGE_LABELS.map((_, index) => {
    if (done[index]) {
      return 'done'
    }
    if (index !== firstPending) {
      return 'pending'
    }
    return state.phase === 'halted' ? 'failed' : 'active'
  })
}

/**
 * Whether both sellers are still working, with neither bid in yet.
 *
 * The state the screen spends its first seconds in, and the one worth naming:
 * it is what "two suppliers bidding at the same time" looks like.
 *
 * @param state - The current run state.
 * @returns True when every column is mid-bid.
 */
export function bothBidding(state: RunState): boolean {
  const columns = Object.values(state.columns)
  return columns.length > 0 && columns.every((column) => column.phase === 'bidding')
}

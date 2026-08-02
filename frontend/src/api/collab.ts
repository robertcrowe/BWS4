// Built with Spec4 AI - https://spec4.ai
import { fetchEventSource } from '@microsoft/fetch-event-source'

/**
 * Typed client for the multi-agent collaboration endpoints.
 *
 * One client per example app, matching `orchestrated.ts` and `planning.ts`,
 * including their error messages: `fetch` rejects identically for "the backend
 * isn't running" and "the browser blocked the response for CORS", so the
 * unreachable message names both rather than saying something unactionable.
 *
 * The identity cards are fetched rather than duplicated here. They are what the
 * negotiation is validated against server-side, so a frontend copy would be a
 * second source of truth free to drift from the one the run actually uses.
 *
 * These interfaces mirror the backend's A2A-shaped models, camelCase included —
 * that spelling is the protocol's, not a TypeScript convention, and translating
 * it here would hide the one thing the shape is meant to show.
 */

/** The organisation standing behind an agent. */
export interface AgentProvider {
  organization: string
  url: string | null
}

/** One capability an agent advertises it can perform. */
export interface AgentSkill {
  id: string
  name: string
  description: string
  tags: string[]
  examples: string[]
}

/**
 * Transport-level features an agent supports.
 *
 * Every flag is `false` for every agent here, and that is accurate rather than
 * unfinished: there is no network transport to stream over or push across.
 */
export interface AgentCapabilities {
  streaming: boolean
  pushNotifications: boolean
  stateTransitionHistory: boolean
}

/** What a peer publishes about itself, as A2A shapes it. */
export interface AgentCard {
  name: string
  description: string
  version: string
  protocolVersion: string
  url: string | null
  provider: AgentProvider
  capabilities: AgentCapabilities
  skills: AgentSkill[]
  /** This showcase's own field, not A2A's. Always `'none'`: every agent here is knowledge-only. */
  toolAccess: string
  defaultInputModes: string[]
  defaultOutputModes: string[]
}

/**
 * One participant: its bus address and presentation, plus its published card.
 *
 * `id`, `role` and `color` sit beside the card rather than inside it because an
 * `AgentCard` describes an agent without addressing one — the same split the
 * backend keeps so its protocol module stays a faithful statement of A2A.
 */
export interface IdentityCard {
  id: string
  role: string
  color: string
  card: AgentCard
}

/** Response body of GET /api/collab/identity-cards. */
export interface IdentityCardsResponse {
  agents: IdentityCard[]
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/** A failed collaboration request, carrying the backend's own explanation where there was one. */
export class CollabRequestError extends Error {
  readonly code: string

  constructor(message: string, code: string, cause?: unknown) {
    super(message, { cause })
    this.name = 'CollabRequestError'
    this.code = code
  }
}

/**
 * `fetch` rejects identically whether the backend is down or the browser
 * blocked the response for CORS, so the message names both rather than saying
 * something the reader cannot act on. Matches `orchestrated.ts`.
 */
function unreachable(url: string, cause: unknown): CollabRequestError {
  return new CollabRequestError(
    `Could not reach the backend at ${url}. Either it isn't running, or this page's origin (${window.location.origin}) doesn't match the backend's CORS_ORIGIN setting.`,
    'unreachable',
    cause,
  )
}

/**
 * Fetch the three peer identity cards.
 *
 * Static server-side configuration: no model call, no quota, nothing the
 * visitor supplied. It answers on a deployment with no provider keys at all,
 * which is what makes it safe to render on page load.
 *
 * @returns The buyer and both rival sellers, each with its A2A-shaped card.
 * @throws CollabRequestError if the backend is unreachable or returns non-2xx.
 */
export async function fetchIdentityCards(): Promise<IdentityCardsResponse> {
  const url = `${API_BASE_URL}/api/collab/identity-cards`

  let response: Response
  try {
    response = await fetch(url)
  } catch (cause) {
    throw unreachable(url, cause)
  }

  if (!response.ok) {
    throw new CollabRequestError(
      `The backend returned ${response.status} for ${url}.`,
      'request_failed',
    )
  }

  return (await response.json()) as IdentityCardsResponse
}

// ---------------------------------------------------------------------------
// The negotiation run
// ---------------------------------------------------------------------------

/** One seller's offer at one stage, as the backend emits it. */
export interface BidEvent {
  stage: string
  seller_id: string
  unit_price: number
  quantity: number
  delivery_days: number
  warranty_months: number
  notes: string
  concessions_made: string[]
  /** Present only on a bid re-issued by the differentiation check. */
  reissued?: boolean
}

/** The buyer's targeted push on one seller, on one term. */
export interface CounterOfferEvent {
  seller_id: string
  targeted_term: string
  ask: string
  justification: string
}

/** The buyer's own score for one seller on one priority. */
export interface PriorityScoreEvent {
  seller_id: string
  priority: string
  score: number
  comment: string
}

/** The buyer's decision, with the working it committed to first. */
export interface AwardEvent {
  winner_id: string
  per_priority_scoring: PriorityScoreEvent[]
  rationale: string
  priority_references: string[]
  runner_up_note: string
}

/** One row of the server's message log. */
export interface PeerMessageRow {
  sequence: number
  timestamp: string
  sender: string
  recipient: string
  stage: string
  work_item: Record<string, unknown>
}

/** What a run's cost is declared to be, before it starts. */
export interface DeclaredBudget {
  total: number
  negotiation: number
  explanation: number
}

/**
 * A stage event from `POST /api/collab/run`.
 *
 * Discriminated on `kind`, which is also the SSE event name. Anything the
 * client does not recognise is ignored rather than crashed on, so the backend
 * can add a stage without breaking a deployed frontend.
 */
export type RunEvent =
  | {
      kind: 'quotation_request'
      stage: string
      request: { text: string; goods: string; baseline_requirement: string }
      model_calls: number
      declared_budget: DeclaredBudget
      sellers: string[]
    }
  | ({ kind: 'bid'; stage: string } & BidEvent)
  | { kind: 'counter_offers'; stage: string; offers: CounterOfferEvent[]; repairs: string[] }
  | { kind: 'routing'; stage: string; delivered: string[]; model_calls: number }
  | { kind: 'degraded'; stage: string; seller_id: string; status: string }
  | {
      kind: 'award'
      stage: string
      award: AwardEvent
      reconciled: boolean
      reconciliation_note: string
      model_calls_used: number
      negotiation_stage_calls: number
    }
  | ({ kind: 'reveal'; stage: string } & RevealPayload)
  | ({ kind: 'sensitivity'; stage: string } & SensitivityPayload)
  | {
      kind: 'message_log'
      stage: string
      messages: PeerMessageRow[]
      seller_to_seller_count: number
    }
  | {
      kind: 'error'
      stage: string
      code: string
      message: string
      outcome?: string
      remaining?: number
      cap?: number
      resets_at?: string
    }

/** The event names the server sends. Anything else is ignored, not crashed on. */
const RUN_EVENT_NAMES = new Set([
  'quotation_request',
  'bid',
  'counter_offers',
  'routing',
  'degraded',
  'award',
  'reveal',
  'sensitivity',
  'message_log',
  'error',
])

/** Options for {@link startNegotiation}. */
export interface StartNegotiationOptions {
  scenarioId: string
  weightingId: string
  onEvent: (event: RunEvent) => void
  signal?: AbortSignal
}

/**
 * Start a negotiation and deliver each stage event as it arrives.
 *
 * `@microsoft/fetch-event-source` rather than the browser's `EventSource`,
 * and that is not a preference: `EventSource` is GET-only and a run starts
 * from a POST body. **Do not add a GET variant of the endpoint** to work
 * around it — that forks the API for a transport detail.
 *
 * Three of the library's defaults are wrong for an endpoint that spends quota,
 * and all three are overridden here for the same reasons the planning and
 * orchestrated clients override them:
 *
 * - `openWhenHidden: true`, because the default drops the connection on a
 *   backgrounded tab and *reopens* it — paying for the run twice, silently,
 *   and only for visitors who switch tabs.
 * - `onopen` throws the backend's own explanation, so a 422 on the request
 *   body does not read as a transport fault.
 * - `onerror` rethrows. The default retries forever whenever it *returns*.
 *
 * @param options - The scenario and weighting to run, plus the event sink.
 * @returns A promise resolving when the stream closes.
 * @throws CollabRequestError if the backend is unreachable or rejects the request.
 */
export async function startNegotiation({
  scenarioId,
  weightingId,
  onEvent,
  signal,
}: StartNegotiationOptions): Promise<void> {
  const url = `${API_BASE_URL}/api/collab/run`

  await fetchEventSource(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ scenario_id: scenarioId, weighting_id: weightingId }),
    signal,
    openWhenHidden: true,

    async onopen(response) {
      if (response.ok) {
        return
      }
      const body: unknown = await response.json().catch(() => null)
      const detail =
        typeof body === 'object' && body !== null && 'detail' in body
          ? String((body as { detail: unknown }).detail)
          : `The backend returned ${response.status} for ${url}.`
      throw new CollabRequestError(detail, 'request_failed')
    },

    onmessage(message) {
      if (!RUN_EVENT_NAMES.has(message.event)) {
        return
      }
      onEvent({ kind: message.event, ...JSON.parse(message.data) } as RunEvent)
    },

    onerror(cause) {
      if (cause instanceof CollabRequestError) {
        throw cause
      }
      throw unreachable(url, cause)
    },
  })
}

/** One party's axis-by-axis reveal entry. */
export interface RevealAxis {
  axis: string
  stance: string
  opening_value: number
  final_value: number
  binding_constraint: string | null
  explanation: string
}

/** One party's unsealed block. */
export interface RevealParty {
  party_id: string
  headline: string
  axes: RevealAxis[]
}

/** The post-award unsealing payload. */
export interface RevealPayload {
  parties: RevealParty[]
  /** True when the narration came from the deterministic template. */
  fallback_generated: boolean
  violations: string[]
}

/** The computed half of the sensitivity projection, alongside the narration. */
export interface ComputedProjection {
  original_weights: Record<string, number>
  alternative_weights: Record<string, number>
  alternative_label: string
  original_winner: string
  alternative_winner: string
  outcome: string
  decisive_axes: string[]
}

/** The priority-sensitivity payload. */
export interface SensitivityPayload {
  likely_winner: string
  decisive_dimensions: string[]
  narration: string
  confidence: string
  caveat: string
  fallback_generated: boolean
  violations: string[]
  computed: ComputedProjection | Record<string, never>
}

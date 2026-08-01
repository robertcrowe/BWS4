// Built with Spec4 AI - https://spec4.ai
import { fetchEventSource } from '@microsoft/fetch-event-source'


/**
 * Typed client for the orchestrated-subagents endpoints.
 *
 * One client per example app, matching `planning.ts` and `chainedCalls.ts`,
 * including their error messages: `fetch` rejects identically for "the backend
 * isn't running" and "the browser blocked the response for CORS", so the
 * unreachable message names both rather than saying something unactionable.
 *
 * The roster is fetched rather than duplicated here. It is the closed set the
 * coordinator's delegation is validated against server-side, so a frontend copy
 * that drifted would offer a visitor a specialist the server would refuse.
 */

/** One member of the fixed roster, as the server publishes it. */
export interface Specialist {
  id: string
  displayName: string
  scope: string
  /** Column accent, from the design palette. */
  color: string
}

/** One curated preset question. */
export interface PresetQuestion {
  id: string
  text: string
  /**
   * The pairing a human labelled this question with.
   *
   * A label for offline evaluation, **not** a prediction the UI should show as
   * the answer — displaying it would tell the visitor what the coordinator is
   * about to decide, which is the one thing this app exists to let them watch.
   */
  expectedPairing: string[]
}

/** Response body of GET /api/orchestrated/roster. */
export interface RosterResponse {
  specialists: Specialist[]
  presets: PresetQuestion[]
}

/** One specialist's instruction for this run. */
export interface Brief {
  specialist_id: string
  instruction: string
}

/**
 * The coordinator's decision, streamed as the run's first event.
 *
 * `fit_quality` is the coordinator's own honest read on whether the question
 * suits any two of the four. `weak` is not an error — it is the app admitting
 * the pairing is approximate, which the UI shows rather than hides.
 */
export interface DelegationDecision {
  decision_id: string
  chosen_specialists: string[]
  rationale: string
  briefs: Brief[]
  fit_quality: 'strong' | 'weak'
  /** What the run costs, as told to the visitor. */
  model_call_count: number
}

/**
 * A refusal the run reported and streamed, rather than a transport failure.
 *
 * `outcome` is what to branch on: a blocked question, an exhausted hourly
 * allowance and a coordinator failure need different copy — one is fixed by
 * rewording, one by waiting, one by retrying.
 *
 * `moderation_unavailable` is deliberately not folded into `moderation_blocked`.
 * The first means nothing examined the question; telling someone their question
 * was rejected when the checker was simply down is a claim with nothing behind
 * it. It is also the state a deployment sits in with no moderation key set, so
 * it is the common one rather than the exotic one.
 */
export interface RunError {
  outcome:
    | 'moderation_blocked'
    | 'moderation_unavailable'
    | 'usage_limit_reached'
    | 'coordinator_failed'
    | 'invalid_delegation'
  message: string
  decision_id: string
}

/** How one specialist's column is doing before it has an answer. */
export interface SpecialistStatusEvent {
  specialist_id: string
  status: 'running'
}

/**
 * One specialist's settled column.
 *
 * `status` is three-valued and the third value earns its place: `timeout` means
 * the specialist was still working when the run stopped waiting, which is a
 * different thing to show — and to offer — than `failed`.
 */
export interface SpecialistAnswerEvent {
  specialist_id: string
  status: 'ok' | 'failed' | 'timeout'
  answer: string
  key_points: string[]
  error: string | null
}

/** The fan-out finished with at least one column filled. */
export interface FanOutComplete {
  decision_id: string
  survivors: string[]
  model_call_count: number
}

/**
 * A refusal on the dispatch stream.
 *
 * `refund_run` is the server saying this attempt should not count against the
 * visitor's session runs — set when both specialists failed and there is
 * nothing to show for the run.
 */
export interface DispatchError extends RunError {
  retryable: boolean
  refund_run?: boolean
}

/** One place the two specialists cannot both be acted on. */
export interface Contradiction {
  claim_a: string
  claim_b: string
  specialist_a: string | null
  specialist_b: string | null
}

/**
 * How the two independent answers relate.
 *
 * `comparable` is false when only one specialist answered — the server forces
 * it and empties every list, so a one-sided run cannot render as a comparison.
 * Contradictions reaching the client have already survived a server-side
 * traceability check: each one's quotes were found in the answer it is
 * attributed to, so a fabricated conflict never gets this far.
 */
export interface DisagreementNote {
  summary: string
  agreements: string[]
  complements: string[]
  contradictions: Contradiction[]
  comparable: boolean
}

/** The run's final output. */
export interface MergedAnswerEvent {
  decision_id: string
  text: string
  /** The specialists that actually contributed, as the server recorded them. */
  sources_used: string[]
  disagreement_note: DisagreementNote
  model_call_count: number
}

/** One received event, discriminated by its SSE event name. */
export type RunEvent =
  | { name: 'delegation'; data: DelegationDecision }
  | { name: 'error'; data: RunError }

/** One received event on the dispatch stream. */
export type DispatchEvent =
  | { name: 'specialist_status'; data: SpecialistStatusEvent }
  | { name: 'specialist_answer'; data: SpecialistAnswerEvent }
  | { name: 'fan_out_complete'; data: FanOutComplete }
  | { name: 'merged_answer'; data: MergedAnswerEvent }
  | { name: 'error'; data: DispatchError }

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/** A failure the backend described, or an unreachable one. */
export class OrchestratedRequestError extends Error {
  readonly code: string
  readonly status: number

  constructor(message: string, code: string, status: number, cause?: unknown) {
    super(message, { cause })
    this.name = 'OrchestratedRequestError'
    this.code = code
    this.status = status
  }
}

function unreachable(cause: unknown): OrchestratedRequestError {
  return new OrchestratedRequestError(
    `Could not reach the backend at ${API_BASE_URL}. Either it isn't running, ` +
      `or this page's origin (${window.location.origin}) doesn't match the ` +
      `backend's CORS_ORIGIN setting.`,
    'unreachable',
    0,
    cause,
  )
}

/**
 * Fetch the fixed specialist roster and the curated preset questions.
 *
 * Static server-side configuration: it spends no quota and calls no model, so
 * it is safe to cache indefinitely and safe to fetch on mount.
 *
 * @returns The four specialists and the curated presets.
 * @throws OrchestratedRequestError if the request cannot be made, is blocked, or returns non-2xx.
 */
export async function fetchRoster(): Promise<RosterResponse> {
  const url = `${API_BASE_URL}/api/orchestrated/roster`

  let response: Response
  try {
    response = await fetch(url)
  } catch (cause) {
    throw unreachable(cause)
  }

  if (!response.ok) {
    throw new OrchestratedRequestError(
      `The backend returned ${response.status} for ${url}.`,
      'request_failed',
      response.status,
    )
  }

  return (await response.json()) as RosterResponse
}


/** The event names the server sends. Anything else is ignored rather than crashed on. */
const RUN_EVENT_NAMES = new Set(['delegation', 'error'])

export interface StartRunOptions {
  question: string
  /**
   * The preset this question came from, if any.
   *
   * A claim, not a credential: the server re-checks that the text byte-matches
   * the stored preset before letting it skip the moderation gate.
   */
  presetId?: string | null
  /** Called once per event, in arrival order. */
  onEvent: (event: RunEvent) => void
  /** Aborts the run. The server sees the disconnect and stops working. */
  signal?: AbortSignal
}

/**
 * Start a run and stream its events back.
 *
 * `EventSource` cannot be used: it is GET-only and a run starts from a POST
 * body. Three of `fetchEventSource`'s defaults are wrong for an endpoint that
 * spends model allowance and are overridden here, for the reasons the planning
 * client documents at length — `openWhenHidden` would re-run the whole thing
 * when a backgrounded tab returns, `onerror` retries forever unless it throws,
 * and the default `onopen` reports a rejected body as a transport fault.
 *
 * @param options - The question, the optional preset claim, the per-event callback and an abort signal.
 * @returns A promise resolving when the stream closes normally.
 * @throws OrchestratedRequestError if the backend is unreachable or the run is rejected.
 */
export async function startRun({
  question,
  presetId = null,
  onEvent,
  signal,
}: StartRunOptions): Promise<void> {
  const url = `${API_BASE_URL}/api/orchestrated/run`

  await fetchEventSource(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ question, preset_id: presetId }),
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
          : `The backend returned ${response.status}.`
      throw new OrchestratedRequestError(detail, 'request_failed', response.status)
    },

    onmessage(message) {
      if (!RUN_EVENT_NAMES.has(message.event)) {
        return
      }
      onEvent({ name: message.event, data: JSON.parse(message.data) } as RunEvent)
    },

    onerror(cause) {
      // Rethrowing stops the library's retry loop. Returning would retry, and
      // this endpoint spends allowance.
      if (cause instanceof OrchestratedRequestError) {
        throw cause
      }
      throw unreachable(cause)
    },
  })
}

/** The event names the dispatch stream sends. */
const DISPATCH_EVENT_NAMES = new Set([
  'specialist_status',
  'specialist_answer',
  'fan_out_complete',
  'merged_answer',
  'error',
])

export interface DispatchOptions {
  /** The delegation being confirmed. Single-use: the server redeems its hold. */
  decisionId: string
  /** The decision exactly as it was shown. Re-validated server-side. */
  decision: DelegationDecision
  /** The question the decision was made for. */
  question: string
  /** Called once per event, in arrival order. */
  onEvent: (event: DispatchEvent) => void
  /** Aborts the fan-out. The server sees the disconnect and stops the branches. */
  signal?: AbortSignal
}

/**
 * Give the go-ahead and stream both specialists' columns as they fill.
 *
 * This is the human-in-the-loop gate: a second request, made only when the
 * visitor has read the delegation and asked for it. Nothing here may ever be
 * called from an effect that fires on a decision arriving.
 *
 * The same three `fetchEventSource` defaults are overridden as on the run
 * stream, and the reason bites harder here: a reopened connection on a
 * backgrounded tab would post the same `decision_id` again, which the server
 * refuses — so the visitor would lose the run rather than pay for it twice.
 *
 * @param options - The decision being confirmed, the question, a per-event callback and an abort signal.
 * @returns A promise resolving when the stream closes normally.
 * @throws OrchestratedRequestError if the backend is unreachable or the dispatch is rejected.
 */
export async function dispatchSpecialists({
  decisionId,
  decision,
  question,
  onEvent,
  signal,
}: DispatchOptions): Promise<void> {
  const url = `${API_BASE_URL}/api/orchestrated/dispatch`

  await fetchEventSource(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ decision_id: decisionId, decision, question }),
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
          : `The backend returned ${response.status}.`
      throw new OrchestratedRequestError(detail, 'request_failed', response.status)
    },

    onmessage(message) {
      if (!DISPATCH_EVENT_NAMES.has(message.event)) {
        return
      }
      onEvent({ name: message.event, data: JSON.parse(message.data) } as DispatchEvent)
    },

    onerror(cause) {
      if (cause instanceof OrchestratedRequestError) {
        throw cause
      }
      throw unreachable(cause)
    },
  })
}

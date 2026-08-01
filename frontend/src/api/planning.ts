// Built with Spec4 AI - https://spec4.ai
/**
 * Typed streaming client for the planning-agent endpoint.
 *
 * Unlike every other client in this directory, a planning run is not a
 * request/response — the server emits its plan, then each step result, then the
 * itinerary, and the visitor is meant to see each as it lands. So this module
 * exposes a stream with a callback rather than a promise of a body.
 *
 * **`EventSource` cannot be used here.** The browser's native SSE client is
 * GET-only, and a run starts from a POST body (city and interests). That is the
 * entire reason `@microsoft/fetch-event-source` is a dependency.
 */

import { fetchEventSource } from '@microsoft/fetch-event-source'

/** What the visitor asked for. Sent as the POST body. */
export interface PlanningGoal {
  city: string
  interests: string
}

/** A research step runs the web-search tool; the single synthesis step composes the itinerary. */
export type PlanStepKind = 'research' | 'synthesis'

/**
 * One step of the planner's decomposition, shown before anything executes.
 *
 * These field names come from the capability specification and are mirrored
 * exactly by `backend/app/planning/schemas.py`. They are a contract, not a
 * style choice — renaming one here breaks the wire silently, because JSON
 * carries no types.
 */
export interface PlanStep {
  index: number
  kind: PlanStepKind
  description: string
  /** The search this step will run, or null for the synthesis step. */
  search_query: string | null
}

/** The `plan` event: the decomposition, sent before any step executes. */
export interface Plan {
  goal: string
  steps: PlanStep[]
  /** Set when the planner over-planned and steps were dropped for budget. */
  trimmed_note: string | null
}

/** One web result a research step actually retrieved. */
export interface SearchResult {
  title: string
  url: string
  snippet: string
}

/**
 * The `step_result` event: one executed step's outcome.
 *
 * `completed` with an empty `sources` list is a real and informative outcome —
 * the search ran and the web had little to say. `failed` means the step could
 * not be carried out at all.
 */
export interface StepResult {
  step_index: number
  status: 'completed' | 'failed'
  summary: string
  sources: SearchResult[]
}

/** One part of the composed day. */
export interface ItineraryBlock {
  time_of_day: 'morning' | 'afternoon' | 'evening'
  activity: string
  why_it_matches: string
  /** Plan step indices whose research supports this block. Empty is honest, not missing. */
  source_refs: number[]
}

/** The `itinerary` event: the synthesis step's output, which ends the stream. */
export interface Itinerary {
  city: string
  blocks: ItineraryBlock[]
}

/**
 * The `error` event: a categorised failure that did not break the stream.
 *
 * The run answers 200 and reports trouble this way so results already streamed
 * stay on screen. `code` is what to branch on — `usage_limit_reached` resets at
 * the top of the hour and cannot be retried into working, while `synthesis_failed` can.
 */
export interface PlanningRunError {
  code: string
  message: string
  steps_completed?: number
  details?: string[]
}

/** What the visitor reviewed, sent back to re-compose an itinerary. */
export interface RetrySynthesisRequest {
  goal: PlanningGoal
  plan: Plan
  results: StepResult[]
}

/**
 * One received event, discriminated by its SSE event name.
 *
 * Named events rather than a `type` field inside the JSON: the server sets the
 * SSE `event:` line, so the discriminator is part of the transport and a
 * payload that failed to parse can still be attributed to the right kind.
 */
export type PlanningEvent =
  | { name: 'plan'; data: Plan }
  | { name: 'step_result'; data: StepResult }
  | { name: 'itinerary'; data: Itinerary }
  | { name: 'error'; data: PlanningRunError }

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/** A failure the stream reported, carrying its machine-readable code. */
export class PlanningRequestError extends Error {
  readonly code: string
  readonly status: number

  constructor(message: string, code: string, status: number, cause?: unknown) {
    super(message, { cause })
    this.name = 'PlanningRequestError'
    this.code = code
    this.status = status
  }
}

function unreachable(cause: unknown): PlanningRequestError {
  return new PlanningRequestError(
    `Could not reach the backend at ${API_BASE_URL}. Either it isn't running, ` +
      `or this page's origin (${window.location.origin}) doesn't match the ` +
      `backend's CORS_ORIGIN setting.`,
    'unreachable',
    0,
    cause,
  )
}

/** The event names the server sends. Anything else is ignored rather than crashed on. */
const EVENT_NAMES = new Set(['plan', 'step_result', 'itinerary', 'error'])

/** Response body of POST /api/planning/plan. */
export interface PlanResponse {
  plan: Plan
  trimmed_note: string | null
  /** True when the planner's first attempt failed the checker and was retried. */
  replanned: boolean
  model: string
  calls_used: number
  call_ceiling: number
}

/**
 * Produce a plan for the visitor to review. **Executes nothing.**
 *
 * The first half of the two-phase invocation. Execution needs a separate call
 * to `streamPlanningRun`, which is the visitor's explicit go-ahead — there is
 * no path from here to an executor call.
 *
 * @param goal - The city and interests to plan around.
 * @returns The plan, plus what it cost and whether it needed a second attempt.
 * @throws PlanningRequestError if the request cannot be made, is blocked, or is rejected.
 */
export async function fetchPlan(goal: PlanningGoal): Promise<PlanResponse> {
  const url = `${API_BASE_URL}/api/planning/plan`

  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(goal),
    })
  } catch (cause) {
    throw unreachable(cause)
  }

  const body: unknown = await response.json().catch(() => null)

  if (!response.ok) {
    throw errorFrom(body, response.status)
  }

  return body as PlanResponse
}

/**
 * Re-compose the itinerary from research that already completed.
 *
 * The capability's mitigation for a failed synthesis step. It costs no run
 * allowance -- the visitor already spent one on the research they are looking
 * at -- and re-running the research would produce different findings, so the
 * itinerary that arrived would not be the one their step results support.
 *
 * @param request - The goal, the executed plan, and its results.
 * @returns The freshly composed itinerary.
 * @throws PlanningRequestError if the request cannot be made, is blocked, or is rejected.
 */
export async function retrySynthesis({
  goal,
  plan,
  results,
}: RetrySynthesisRequest): Promise<Itinerary> {
  const url = `${API_BASE_URL}/api/planning/retry-synthesis`

  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...goal, plan, results }),
    })
  } catch (cause) {
    throw unreachable(cause)
  }

  const body: unknown = await response.json().catch(() => null)

  if (!response.ok) {
    throw errorFrom(body, response.status)
  }

  return (body as { itinerary: Itinerary }).itinerary
}

export interface StreamPlanningRunOptions {
  goal: PlanningGoal
  /**
   * The plan the visitor reviewed, sent back as their explicit go-ahead.
   *
   * The server keeps nothing between the two requests, so the plan travels
   * back through the client. It is re-validated on arrival — this is the
   * advance signal, not a licence to execute arbitrary steps.
   */
  plan: Plan
  /** Called once per event, in arrival order. */
  onEvent: (event: PlanningEvent) => void
  /** Aborts the run. The server sees the disconnect and stops working. */
  signal?: AbortSignal
}

/**
 * POST a goal and stream the run's events back.
 *
 * Three of `fetchEventSource`'s defaults are wrong for a quota-spending
 * endpoint and are overridden below. Each would be a silent fault rather than a
 * visible one, which is why they are worth naming:
 *
 * 1. **`openWhenHidden` defaults to `false`**, meaning the library drops the
 *    connection when the tab is backgrounded and *reopens* it on return — which
 *    for this endpoint means starting a second run and spending the quota
 *    again. Set to `true`, so a backgrounded tab keeps the one run it started.
 * 2. **`onerror` retries forever by default** if it returns. Rethrowing is what
 *    makes a failure terminal; without it a backend that is down is hammered in
 *    a loop.
 * 3. **The default `onopen` throws a generic error** on a non-2xx. Replaced so
 *    a 422 from the request body is reported as the validation failure it is.
 *
 * @param options - The goal, the per-event callback, and an optional abort signal.
 * @returns A promise resolving when the stream closes normally.
 * @throws PlanningRequestError if the backend is unreachable or the run fails.
 */
export async function streamPlanningRun({
  goal,
  plan,
  onEvent,
  signal,
}: StreamPlanningRunOptions): Promise<void> {
  const url = `${API_BASE_URL}/api/planning/run`

  await fetchEventSource(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ ...goal, plan }),
    signal,
    openWhenHidden: true,

    async onopen(response) {
      if (response.ok) {
        return
      }
      const body: unknown = await response.json().catch(() => null)
      throw errorFrom(body, response.status)
    },

    onmessage(message) {
      if (!EVENT_NAMES.has(message.event)) {
        return
      }
      onEvent({
        name: message.event,
        data: JSON.parse(message.data),
      } as PlanningEvent)
    },

    onerror(cause) {
      // Rethrowing stops the library's retry loop and rejects the promise.
      // Returning anything here would retry instead — see the note above.
      if (cause instanceof PlanningRequestError) {
        throw cause
      }
      throw unreachable(cause)
    },
  })
}

/** Pull a message and code out of an error response, tolerating FastAPI's own 422 shape. */
function errorFrom(body: unknown, status: number): PlanningRequestError {
  if (typeof body === 'object' && body !== null) {
    const record = body as { detail?: unknown; code?: unknown }
    const code = typeof record.code === 'string' ? record.code : 'request_failed'

    if (typeof record.detail === 'string') {
      return new PlanningRequestError(record.detail, code, status)
    }
    if (Array.isArray(record.detail)) {
      const first = record.detail[0] as { msg?: string } | undefined
      if (first?.msg) {
        return new PlanningRequestError(
          first.msg.replace(/^Value error,\s*/, ''),
          'invalid_request',
          status,
        )
      }
    }
  }
  return new PlanningRequestError(`The backend returned ${status}.`, 'request_failed', status)
}

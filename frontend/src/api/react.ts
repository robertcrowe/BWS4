// Built with Spec4 AI - https://spec4.ai
import { fetchEventSource } from '@microsoft/fetch-event-source'

/**
 * Typed client for the ReAct loop endpoints.
 *
 * One client per example app, matching `collab.ts`, `orchestrated.ts` and
 * `planning.ts`, including their error messages: `fetch` rejects identically
 * for "the backend isn't running" and "the browser blocked the response for
 * CORS", so the unreachable message names both rather than saying something
 * the reader cannot act on.
 *
 * The presets are fetched rather than duplicated here. The question a run
 * actually asks is resolved server-side from the same constants, so a frontend
 * copy would be a second source of truth free to drift from the one the loop
 * uses — and it would put one question on screen while another went to the
 * model.
 *
 * **There is no `cycleBudget` option on the run request, and none should be
 * added.** The budget is server-fixed at eight search cycles; the design mock's
 * 3–6 select is superseded by the stack spec's `react_run_call_budget`
 * decision. The run reserves its whole worst case before the first cycle, so a
 * client-supplied budget would let a caller reserve one number and spend
 * another.
 */

/** One curated multi-hop question, as the selector sees it. */
export interface ReactPreset {
  id: string
  /** Short chip text. Deliberately does not resolve any of the question's hops. */
  label: string
  /** The question put to the model, verbatim. */
  question: string
  /** How many facts the question chains. */
  hopCount: number
  /** True for the presets curated so every hop needs a live observation. */
  guaranteedFullyObserved: boolean
}

/** Response body of GET /api/react/presets. */
export interface ReactPresetsResponse {
  presets: ReactPreset[]
  setVersion: string
  /** The server-fixed search-cycle ceiling. Published so nothing hardcodes it. */
  cycleBudget: number
}

/** One search result, rendered verbatim as part of a cycle's observation. */
export interface ObservationSnippet {
  /** 1-based position within its observation, as the provider ranked them. */
  idx: number
  title: string
  snippet: string
  url: string
  /** Rendered as "undated" when null — an empty slot reads as "recent". */
  published_date: string | null
  /** True when the snippet was cut to fit the model's context. */
  truncated: boolean
}

/**
 * What happened when a query was issued.
 *
 * Three values, not two, and the third is why the UI needs this: an empty
 * result and an unreachable provider both show no snippets and are different
 * facts — one is the web's answer to the question, the other is the
 * demonstration failing. They get different visible states.
 */
export type ObservationStatus = 'ok' | 'empty' | 'unavailable'

/** Whether the final answer's citations point at observations that exist. */
export interface GroundingAudit {
  all_cited_present: boolean
  cited: number[]
  unverified: number[]
}

/** Where one hop's fact came from, after the server's cross-checks. */
export interface HopAnnotation {
  cycle_index: number
  fact: string
  source: 'observation' | 'model_knowledge' | 'mixed'
  /** The cycle whose observation supplies it. Null once downgraded. */
  supporting_cycle: number | null
  note: string
}

/**
 * The annotation panel's payload.
 *
 * `all_hops_observed` is **derived on the server** from the annotations that
 * survived its cross-checks — the model has no field to assert it with. The
 * panel may therefore state it; it could not if the model had claimed it.
 */
export interface AnnotationResult {
  hops: HopAnnotation[]
  all_hops_observed: boolean
  observed_count: number
  recalled_count: number
  dropped: string[]
  downgraded: number[]
}

/** Why a run ended without an answer. */
export type ExhaustionReason =
  | 'search_ceiling'
  | 'malformed_step'
  | 'search_unavailable'
  | 'model_unavailable'
  | 'wall_clock'
  | 'call_budget' 

/**
 * An event from `POST /api/react/run`.
 *
 * Discriminated on `kind`, which is also the SSE event name. Anything the
 * client does not recognise is ignored rather than crashed on, so the backend
 * can add an event type without breaking a deployed frontend.
 *
 * Thought, action, observation and counter are four events for one cycle,
 * deliberately: they are separated in time by seconds, and the order is the
 * thing the app exists to show.
 */
export type ReactRunEvent =
  | {
      kind: 'run_started'
      run_id: string
      question: string
      question_source: 'preset' | 'custom'
      preset_id: string | null
      cycle_budget: number
      runs_remaining: number
      stub: boolean
    }
  | { kind: 'cycle_thought'; cycle: number; thought: string; stub: boolean }
  | {
      kind: 'cycle_action'
      cycle: number
      action_kind: 'search' | 'answer'
      query: string | null
      rationale: string
      stub: boolean
    }
  | {
      kind: 'cycle_observation'
      /** 1-based observation number — the value a final answer cites. */
      index: number
      /** The exact query issued, verbatim. */
      query: string
      results: ObservationSnippet[]
      is_empty: boolean
      status: ObservationStatus
      /** Why the search could not run. Null unless `status` is `unavailable`. */
      detail: string | null
      truncated: boolean
      stub: boolean
    }
  | { kind: 'cycle_counter'; searches_used: number; cycle_budget: number; stub: boolean }
  | {
      kind: 'final_answer'
      run_id: string
      answer: string
      observation_cycles: number[]
      audit: GroundingAudit
      searches_used: number
      cycle_budget: number
      stub: boolean
    }
  | {
      kind: 'budget_exhausted'
      run_id: string
      reason: ExhaustionReason
      unresolved: string[]
      partial_findings: number[]
      searches_used: number
      cycle_budget: number
      stub: boolean
    }
  | ({ kind: 'hop_annotations' } & AnnotationResult)
  | { kind: 'error'; code: string; message: string; stub: boolean }

/** The event names the server sends. Anything else is ignored, not crashed on. */
const RUN_EVENT_NAMES = new Set([
  'run_started',
  'cycle_thought',
  'cycle_action',
  'cycle_observation',
  'cycle_counter',
  'final_answer',
  'budget_exhausted',
  'hop_annotations',
  'error',
])

/** The three ways a stream stops. Exactly one arrives, and it is last. */
export const TERMINAL_EVENT_KINDS = new Set(['final_answer', 'budget_exhausted', 'error'])

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/** A failed ReAct request, carrying the backend's own explanation where there was one. */
export class ReactRequestError extends Error {
  readonly code: string

  constructor(message: string, code: string, cause?: unknown) {
    super(message, { cause })
    this.name = 'ReactRequestError'
    this.code = code
  }
}

/**
 * `fetch` rejects identically whether the backend is down or the browser
 * blocked the response for CORS, so the message names both.
 */
function unreachable(url: string, cause: unknown): ReactRequestError {
  return new ReactRequestError(
    `Could not reach the backend at ${url}. Either it isn't running, or this page's origin (${window.location.origin}) doesn't match the backend's CORS_ORIGIN setting.`,
    'unreachable',
    cause,
  )
}

/** The wire shape of one preset, before it is camel-cased for the components. */
interface PresetWire {
  id: string
  label: string
  question: string
  hop_count: number
  guaranteed_fully_observed: boolean
}

interface PresetsWire {
  presets: PresetWire[]
  set_version: string
  cycle_budget: number
}

/**
 * Fetch the five curated multi-hop questions.
 *
 * Static server-side configuration: no model call, no quota, nothing the
 * visitor supplied, and — because the catalogue stores questions only — no
 * answer to any of them. It answers on a deployment with no provider keys at
 * all, which is what makes it safe to fetch on page load.
 *
 * @returns The presets, the catalogue version, and the run's cycle budget.
 * @throws ReactRequestError if the backend is unreachable or returns non-2xx.
 */
export async function fetchReactPresets(): Promise<ReactPresetsResponse> {
  const url = `${API_BASE_URL}/api/react/presets`

  let response: Response
  try {
    response = await fetch(url)
  } catch (cause) {
    throw unreachable(url, cause)
  }

  if (!response.ok) {
    throw new ReactRequestError(
      `The backend returned ${response.status} for ${url}.`,
      'request_failed',
    )
  }

  const body = (await response.json()) as PresetsWire
  return {
    presets: body.presets.map((preset) => ({
      id: preset.id,
      label: preset.label,
      question: preset.question,
      hopCount: preset.hop_count,
      guaranteedFullyObserved: preset.guaranteed_fully_observed,
    })),
    setVersion: body.set_version,
    cycleBudget: body.cycle_budget,
  }
}

/** The advisory verdict on a visitor's own question. */
export interface QuestionSuitability {
  verdict: 'multi_hop_live' | 'multi_hop_static' | 'single_hop' | 'unanswerable'
  estimated_hops: number
  requires_live_info: boolean
  live_hop_description: string | null
  exercises_loop: boolean
  confidence: 'low' | 'medium' | 'high'
  /** One plain sentence, already sanitised server-side. Safe to render verbatim. */
  visitor_message: string
}

/** Response body of POST /api/react/suitability. */
export interface SuitabilityResponse {
  /** Null is the neutral "unknown" state — every failure path resolves to it. */
  verdict: QuestionSuitability | null
  checks_remaining: number
}

/** Longest question the server will accept. Enforced client-side too. */
export const MAX_QUESTION_CHARS = 300

/**
 * Ask whether a free-form question will exercise the loop.
 *
 * **Advisory only.** The caller must never let the result — or its absence, or
 * a failure of this call — decide whether Start is enabled. A null `verdict` is
 * the ordinary neutral state, not an error: the server resolves a timeout, an
 * exhausted model chain, a spent session cap and a twice-invalid response all
 * to the same thing, because the visitor's response to each is identical.
 *
 * A moderation refusal is the one case that *is* an error, and it arrives as a
 * 422 (reword it) or a 503 (nothing could check it) — kept apart because one
 * the visitor can fix and the other they cannot.
 *
 * @param question - The visitor's own question.
 * @param sessionId - The browser session, for the server's per-session check cap.
 * @returns The verdict or the neutral state, plus remaining checks.
 * @throws ReactRequestError on a moderation refusal or an unreachable backend.
 */
export async function checkSuitability(
  question: string,
  sessionId: string,
): Promise<SuitabilityResponse> {
  const url = `${API_BASE_URL}/api/react/suitability`

  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ visitor_question: question, session_id: sessionId }),
    })
  } catch (cause) {
    throw unreachable(url, cause)
  }

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : `The backend returned ${response.status} for ${url}.`
    throw new ReactRequestError(
      detail,
      response.status === 422 ? 'moderation_blocked' : 'moderation_unavailable',
    )
  }

  return (await response.json()) as SuitabilityResponse
}

/** One stored cycle, as `GET /api/react/run/{run_id}` returns it. */
export interface StoredCycle {
  cycle: number
  thought: string
  action: { kind: 'search' | 'answer'; query: string | null }
  observation: {
    index: number
    query: string
    results: ObservationSnippet[]
    is_empty: boolean
    status: ObservationStatus
    detail: string | null
  } | null
}

/** A completed run's whole persisted trace. */
export interface StoredTrace {
  run_id: string
  created_at: string
  question_origin: string
  searches_used: number
  cycle_budget: number
  ending: 'final_answer' | 'budget_exhausted' | null
  duplicate_queries_blocked: number
  empty_observations: number
  cycle_trace: StoredCycle[]
  terminal_card: Record<string, unknown> | null
}

/**
 * Fetch one completed run's trace by id.
 *
 * **Read from the server rather than from the browser's cached copy**, which is
 * why only the run id is stored locally. The persisted record is the one the
 * grounding audit was computed against; a cached trace could drift from it and
 * would then be showing a visitor something no run actually produced.
 *
 * @param runId - The run's id, from the local allowance record.
 * @returns The whole stored trace.
 * @throws ReactRequestError if the backend is unreachable or has no such run.
 */
export async function fetchReactRun(runId: string): Promise<StoredTrace> {
  const url = `${API_BASE_URL}/api/react/run/${runId}`

  let response: Response
  try {
    response = await fetch(url)
  } catch (cause) {
    throw unreachable(url, cause)
  }

  if (!response.ok) {
    throw new ReactRequestError(
      `The backend returned ${response.status} for ${url}.`,
      response.status === 404 ? 'not_found' : 'request_failed',
    )
  }

  return (await response.json()) as StoredTrace
}

/** Options for {@link startReactRun}. Exactly one question source, as the server requires. */
export interface StartReactRunOptions {
  presetQuestionId?: string
  visitorQuestion?: string
  sessionId: string
  onEvent: (event: ReactRunEvent) => void
  signal?: AbortSignal
}

/**
 * Start a run and deliver each envelope as it arrives.
 *
 * `@microsoft/fetch-event-source` rather than the browser's `EventSource`, and
 * that is not a preference: `EventSource` is GET-only and a run starts from a
 * POST body. **Do not add a GET variant of the endpoint** to work around it —
 * that forks the API for a transport detail.
 *
 * Three of the library's defaults are wrong for an endpoint that spends quota,
 * and all three are overridden here for the reasons the planning, orchestrated
 * and collaboration clients override them. They matter more here than anywhere
 * else in the gallery, because this is its most expensive example per run:
 *
 * - `openWhenHidden: true`, because the default drops the connection on a
 *   backgrounded tab and *reopens* it — paying for the run twice, silently, and
 *   only for visitors who switch tabs.
 * - `onopen` throws the backend's own explanation, so a 422 on the request body
 *   does not read as a transport fault.
 * - `onerror` rethrows. The default retries forever whenever it *returns*.
 *
 * @param options - The question source, the session id, and the event sink.
 * @returns A promise resolving when the stream closes.
 * @throws ReactRequestError if the backend is unreachable or rejects the request.
 */
export async function startReactRun({
  presetQuestionId,
  visitorQuestion,
  sessionId,
  onEvent,
  signal,
}: StartReactRunOptions): Promise<void> {
  const url = `${API_BASE_URL}/api/react/run`

  await fetchEventSource(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({
      preset_question_id: presetQuestionId ?? null,
      visitor_question: visitorQuestion ?? null,
      session_id: sessionId,
    }),
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
      throw new ReactRequestError(detail, 'request_failed')
    },

    onmessage(message) {
      if (!RUN_EVENT_NAMES.has(message.event)) {
        return
      }
      const payload = JSON.parse(message.data) as Record<string, unknown>
      // `kind` is the SSE event name, and the action's own `kind` field would
      // collide with it — so the action's is renamed on the way in rather than
      // one of them silently winning.
      if (message.event === 'cycle_action') {
        const { kind: actionKind, ...rest } = payload
        onEvent({ kind: 'cycle_action', action_kind: actionKind, ...rest } as ReactRunEvent)
        return
      }
      onEvent({ kind: message.event, ...payload } as ReactRunEvent)
    },

    onerror(cause) {
      if (cause instanceof ReactRequestError) {
        throw cause
      }
      throw unreachable(url, cause)
    },
  })
}

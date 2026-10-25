// Built with Spec4 AI - https://spec4.ai
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { useQuery } from '@tanstack/react-query'

/**
 * Typed client for the Router endpoints.
 *
 * One client per example app, matching `react.ts`, including its error
 * messages: `fetch` rejects identically for "the backend isn't running" and
 * "the browser blocked the response for CORS", so the unreachable message names
 * both.
 *
 * The presets are fetched rather than duplicated here. The request a run routes
 * is resolved server-side from the same constants, so a frontend copy would be
 * a second source of truth free to drift.
 */

/** The four route ids, spelled exactly as the backend's `router/constants.py`. */
export type RouteId = 'deterministic_evaluator' | 'single_call' | 'retrieval' | 'search_generation'

/** One curated request, as the selector sees it. */
export interface RouterPreset {
  id: string
  /** The request put to the router, verbatim. */
  request: string
  /**
   * The route that is the right home for this request. Carried so agreement
   * can be computed and explained; never shown before a run is decided.
   */
  expectedRoute: RouteId
  /** One line on why the expected route is the right home. */
  reason: string
  pair: 'conversion' | 'space' | null
  pairRole: 'control' | 'near_miss' | null
}

/** One route as the router is told it. */
export interface RouterRoute {
  id: RouteId
  label: string
  /** The one line the router receives, verbatim. */
  description: string
  /** Position in the cost order, 0 cheapest. */
  costRank: number
}

/** Response body of GET /api/router/presets. */
export interface RouterPresetsResponse {
  presets: RouterPreset[]
  setVersion: string
  /** Top-two score gap at or below which a run is low-confidence. */
  decisionMargin: number
  /** Route ids, cheapest first. */
  costOrder: RouteId[]
  routeDescriptions: RouterRoute[]
  /**
   * The exact string the router prompt receives. Render it verbatim — no
   * trimming, no markdown — or the byte-for-byte claim on the page is false.
   */
  routeDescriptionsBlock: string
  /** Hex SHA-256 of `routeDescriptionsBlock`'s UTF-8 bytes, computed server-side. */
  routeDescriptionsSha256: string
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/** A failed call to a Router endpoint, carrying a machine-readable code. */
export class RouterRequestError extends Error {
  readonly code: string

  constructor(message: string, code: string, cause?: unknown) {
    super(message, { cause })
    this.name = 'RouterRequestError'
    this.code = code
  }
}

/**
 * `fetch` rejects identically whether the backend is down or the browser
 * blocked the response for CORS, so the message names both.
 */
function unreachable(url: string, cause: unknown): RouterRequestError {
  return new RouterRequestError(
    `Could not reach the backend at ${url}. Either it isn't running, or this page's origin (${window.location.origin}) doesn't match the backend's CORS_ORIGIN setting.`,
    'unreachable',
    cause,
  )
}

/** The wire shape of one preset, before it is camel-cased for the components. */
interface PresetWire {
  id: string
  request: string
  expected_route: RouteId
  reason: string
  pair: 'conversion' | 'space' | null
  pair_role: 'control' | 'near_miss' | null
}

interface RouteWire {
  id: RouteId
  label: string
  description: string
  cost_rank: number
}

interface PresetsWire {
  presets: PresetWire[]
  set_version: string
  decision_margin: number
  cost_order: RouteId[]
  route_descriptions: RouteWire[]
  route_descriptions_block: string
  route_descriptions_sha256: string
}

/**
 * Read a FastAPI error body's `detail`, falling back to a status line.
 *
 * The 503 "descriptions not ready" detail is written for visitors, so it is
 * shown rather than replaced with a generic status.
 */
async function errorDetail(response: Response, url: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') {
      return body.detail
    }
  } catch {
    // Not JSON; fall through to the status line.
  }
  return `The backend returned ${response.status} for ${url}.`
}

/**
 * Fetch the six curated requests, the decision margin and the cost order.
 *
 * Static server-side configuration: no model call, no quota, and no answer to
 * any preset, because the catalogue stores requests only.
 *
 * @returns The presets and the fixed decision settings.
 * @throws RouterRequestError if the backend is unreachable or returns non-2xx.
 */
export async function fetchRouterPresets(): Promise<RouterPresetsResponse> {
  const url = `${API_BASE_URL}/api/router/presets`

  let response: Response
  try {
    response = await fetch(url)
  } catch (cause) {
    throw unreachable(url, cause)
  }

  if (!response.ok) {
    throw new RouterRequestError(
      await errorDetail(response, url),
      response.status === 503 ? 'not_ready' : 'request_failed',
    )
  }

  const body = (await response.json()) as PresetsWire
  return {
    presets: body.presets.map((preset) => ({
      id: preset.id,
      request: preset.request,
      expectedRoute: preset.expected_route,
      reason: preset.reason,
      pair: preset.pair,
      pairRole: preset.pair_role,
    })),
    setVersion: body.set_version,
    decisionMargin: body.decision_margin,
    costOrder: body.cost_order,
    routeDescriptions: body.route_descriptions.map((route) => ({
      id: route.id,
      label: route.label,
      description: route.description,
      costRank: route.cost_rank,
    })),
    routeDescriptionsBlock: body.route_descriptions_block,
    routeDescriptionsSha256: body.route_descriptions_sha256,
  }
}

/**
 * TanStack Query hook for the Router presets.
 *
 * Permanently fresh, like the ReAct presets: the catalogue is built from module
 * constants, so refetching returns byte-identical data. Retries are disabled so
 * an unreachable backend surfaces its message at once rather than after a
 * silent back-off.
 *
 * @returns The query result backing the preset list.
 */
export function useRouterPresets() {
  return useQuery({
    queryKey: ['router', 'presets'],
    queryFn: fetchRouterPresets,
    staleTime: Infinity,
    retry: false,
  })
}

/** Longest request a visitor may type. Matches the server's cap. */
export const MAX_REQUEST_CHARS = 300

export type Agreement = 'agreed' | 'misrouted' | 'declined'

/** `run_started`: the run was admitted and its units are held. */
export interface RunStartedEvent {
  kind: 'run_started'
  run_id: string
  request: string
  preset_id: string | null
  units_reserved: number
  /** True for a comparison re-run, which skips the router. */
  is_rerun: boolean
  original_run_id: string | null
}

/** `stage`: progress through the run. */
export interface StageEvent {
  kind: 'stage'
  stage: 'classifying' | 'dispatching'
  message: string
}

/** The low-confidence card's content. */
export interface LowConfidenceCard {
  /** The two top-scoring routes, cheaper first. */
  torn: [RouteId, RouteId]
  dispatched: RouteId
  caveat: string
}

/** `decision`: the decision card. */
export interface DecisionEvent {
  kind: 'decision'
  decision_kind: 'routed' | 'low_confidence' | 'malformed'
  /** The argmax route; null when the router did not choose or was malformed. */
  chosen_route: RouteId | null
  dispatched_route: RouteId
  /** All four uncalibrated scores; null only for a malformed decision. */
  scores: Record<RouteId, number> | null
  /** Model text. Rendered as plain text, never markup. */
  rationale: string | null
  expression: string | null
  /** Presets only. Null for free text and for a malformed decision. */
  agreement: Agreement | null
  expected_route: RouteId | null
  expected_reason: string | null
  low_confidence: LowConfidenceCard | null
  malformed_note: string | null
  /** Set when the evaluator rejected the expression and the request went elsewhere. */
  evaluator_fallback_note: string | null
  classifier_ms: number
  model: string | null
}

/** Unit accounting for a run. */
export interface UnitAccount {
  reserved: number
  used: number
  released: number
}

/** One search result, shown beside the answer so `[n]` resolves. */
export interface RouterSnippet {
  index: number
  title: string
  url: string
  excerpt: string
  /** Rendered as "undated" when null. */
  published_date: string | null
  truncated: boolean
}

/** One retrieved passage, shown beside the answer so `[n]` resolves. */
export interface RouterPassage {
  index: number
  title: string
  excerpt: string
  similarity: number
  cited: boolean
}

/** `answer`: the dispatched route's answer, labelled with its path. */
export interface AnswerEvent {
  kind: 'answer'
  route: RouteId
  route_label: string
  /**
   * `deterministic`: the evaluator's value, no model call. `notice`: a fixed,
   * candid non-answer no model wrote. `failure`: no answer, nothing fabricated.
   */
  answer_kind: 'deterministic' | 'text' | 'notice' | 'failure'
  /** Generated text. Model output: render through the shared Markdown component. */
  text: string | null
  expression: string | null
  evaluator_verdict: 'accepted' | null
  value_display: string | null
  model: string | null
  /** This route's own measured time. */
  elapsed_ms: number
  truncated: boolean
  error: string | null
  /** The exact query sent to search, on the search route. */
  query: string | null
  snippets: RouterSnippet[]
  passages: RouterPassage[]
  /** Cited indices with no source behind them, stripped server-side. */
  invalid_citations: number[]
  /** URLs the model wrote that were not a source's, removed server-side. */
  removed_urls: string[]
  /** The RAG citation audit's verdict on the retrieval route. */
  grounding: 'grounded' | 'unsupported' | null
  model_calls: number
  searches: number
  retrievals: number
}

/**
 * The route taken against the "no router" baseline (one search plus one
 * generation call), with the router's own call as separate overhead.
 */
export interface CostStrip {
  route: RouteId
  route_label: string
  /** What the route spent, and its own measured time. */
  route_taken: { model_calls: number; searches: number; retrievals: number; measured_ms: number }
  /**
   * The baseline. `typical_ms` is the median of real search-route runs, null
   * until five exist. It is never this run's time and must never be shown as one.
   */
  baseline: {
    model_calls: number
    searches: number
    retrievals: number
    typical_ms: number | null
    sample_size: number
  }
  /** The router's classification call. Zero on a re-run, shown as zero. */
  overhead: { model_calls: number; measured_ms: number }
  /** True when the route taken was the baseline itself. */
  saved_nothing: boolean
  notes: string[]
}

/** `run_end`: the run's one ending. The client spends a run on this event only. */
export interface RunEndEvent {
  kind: 'run_end'
  run_id: string
  ending: 'routed_answer' | 'low_confidence'
  dispatched_route: RouteId
  units: UnitAccount
  /** The whole run's measured time, router included. */
  elapsed_ms: number
  cost_strip: CostStrip
  /**
   * True when the comparison re-run may be offered: a preset run dispatched
   * away from its expected route. The server rechecks it on request.
   */
  rerun_eligible: boolean
  is_rerun: boolean
  original_run_id: string | null
}

export type RouterRunEvent =
  | RunStartedEvent
  | StageEvent
  | DecisionEvent
  | AnswerEvent
  | RunEndEvent

const RUN_EVENT_NAMES = new Set(['run_started', 'stage', 'decision', 'answer', 'run_end'])

/** Codes for a run refused before it started. */
export type RefusalCode =
  | 'moderation_blocked'
  | 'moderation_unavailable'
  | 'shared_cap_reached'
  | 'descriptions_not_ready'
  | 'preset_mismatch'
  | 'unknown_preset'
  | 'rerun_unknown'
  | 'rerun_mismatch'
  | 'rerun_ineligible'
  | 'rerun_already_used'
  | 'request_failed'

/** Options for {@link startRouterRun}. */
export interface StartRouterRunOptions {
  request: string
  presetId?: string
  visitId: string
  onEvent: (event: RouterRunEvent) => void
  signal: AbortSignal
}

/** Options for {@link startRouterRerun}. */
export interface StartRouterRerunOptions {
  presetId: string
  originalRunId: string
  visitId: string
  onEvent: (event: RouterRunEvent) => void
  signal: AbortSignal
}

/**
 * Start a run and deliver each event as it arrives.
 *
 * A refusal before the run starts — moderation, the shared cap, descriptions
 * not ready — is an HTTP error, surfaced as a `RouterRequestError` carrying the
 * server's code so the UI can tell the causes apart. **Retries are disabled**:
 * `onerror` rethrows, so `fetch-event-source` never re-POSTs a quota-spending
 * request on its own.
 *
 * @throws RouterRequestError on a refusal or an unreachable backend.
 */
export async function startRouterRun({
  request,
  presetId,
  visitId,
  onEvent,
  signal,
}: StartRouterRunOptions): Promise<void> {
  await streamRouter(
    `${API_BASE_URL}/api/router/run`,
    { request, preset_id: presetId ?? null, visit_id: visitId },
    onEvent,
    signal,
  )
}

/**
 * Re-run a misrouted preset once through its expected route. The router does
 * not run; the server rechecks eligibility itself and refuses an ineligible or
 * repeated re-run with an HTTP error. Retries disabled, as for a run.
 *
 * @throws RouterRequestError on a refusal or an unreachable backend.
 */
export async function startRouterRerun({
  presetId,
  originalRunId,
  visitId,
  onEvent,
  signal,
}: StartRouterRerunOptions): Promise<void> {
  await streamRouter(
    `${API_BASE_URL}/api/router/rerun`,
    { preset_id: presetId, original_run_id: originalRunId, visit_id: visitId },
    onEvent,
    signal,
  )
}

/** POST a body and deliver the event stream, with retries disabled. */
async function streamRouter(
  url: string,
  body: Record<string, unknown>,
  onEvent: (event: RouterRunEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  await fetchEventSource(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
    openWhenHidden: true,

    async onopen(response) {
      if (response.ok) {
        return
      }
      const parsed: unknown = await response.json().catch(() => null)
      const detail =
        typeof parsed === 'object' && parsed !== null && 'detail' in parsed
          ? (parsed as { detail: unknown }).detail
          : null
      if (typeof detail === 'object' && detail !== null && 'code' in detail) {
        const refusal = detail as { code: string; message?: string }
        throw new RouterRequestError(refusal.message ?? refusal.code, refusal.code)
      }
      throw new RouterRequestError(
        typeof detail === 'string' ? detail : `The backend returned ${response.status} for ${url}.`,
        'request_failed',
      )
    },

    onmessage(message) {
      if (!RUN_EVENT_NAMES.has(message.event)) {
        return
      }
      const payload = JSON.parse(message.data) as Record<string, unknown>
      // The decision's and the answer's own `kind` would collide with the
      // event name, so each is renamed on the way in rather than one silently
      // winning.
      if (message.event === 'decision') {
        const { kind: decisionKind, ...rest } = payload
        onEvent({ kind: 'decision', decision_kind: decisionKind, ...rest } as DecisionEvent)
        return
      }
      if (message.event === 'answer') {
        const { kind: answerKind, ...rest } = payload
        onEvent({ kind: 'answer', answer_kind: answerKind, ...rest } as AnswerEvent)
        return
      }
      onEvent({ kind: message.event, ...payload } as RouterRunEvent)
    },

    onerror(cause) {
      if (cause instanceof RouterRequestError) {
        throw cause
      }
      throw unreachable(url, cause)
    },
  })
}

/** One agreement-history cell. `rate` is null until the cell has five rows. */
export interface AgreementCell {
  presetId: string | null
  agreed: number
  disagreed: number
  declined: number
  total: number
  rate: number | null
}

/** Response body of GET /api/router/history. */
export interface RouterHistory {
  presets: AgreementCell[]
  overall: AgreementCell
  baseline: { typicalMs: number | null; sampleSize: number; window: number }
  minObservations: number
}

interface CellWire {
  preset_id: string | null
  agreed: number
  disagreed: number
  declined: number
  total: number
  rate: number | null
}

interface HistoryWire {
  presets: CellWire[]
  overall: CellWire
  baseline: { typical_ms: number | null; sample_size: number; window: number }
  min_observations: number
}

function cellFromWire(cell: CellWire): AgreementCell {
  return {
    presetId: cell.preset_id,
    agreed: cell.agreed,
    disagreed: cell.disagreed,
    declined: cell.declined,
    total: cell.total,
    rate: cell.rate,
  }
}

/**
 * Fetch the shared agreement history and the typical search-route time.
 *
 * @returns The history.
 * @throws RouterRequestError if the backend is unreachable or returns non-2xx.
 */
export async function fetchRouterHistory(): Promise<RouterHistory> {
  const url = `${API_BASE_URL}/api/router/history`

  let response: Response
  try {
    response = await fetch(url)
  } catch (cause) {
    throw unreachable(url, cause)
  }
  if (!response.ok) {
    throw new RouterRequestError(await errorDetail(response, url), 'request_failed')
  }
  const body = (await response.json()) as HistoryWire
  return {
    presets: body.presets.map(cellFromWire),
    overall: cellFromWire(body.overall),
    baseline: {
      typicalMs: body.baseline.typical_ms,
      sampleSize: body.baseline.sample_size,
      window: body.baseline.window,
    },
    minObservations: body.min_observations,
  }
}

/** The TanStack Query key for the history, so a finished run can refetch it. */
export const ROUTER_HISTORY_KEY = ['router', 'history'] as const

/**
 * TanStack Query hook for the shared history. Retries disabled, like every
 * Router query; refetched by the app after each run ends.
 *
 * @returns The query result backing the agreement panel.
 */
export function useRouterHistory() {
  return useQuery({
    queryKey: ROUTER_HISTORY_KEY,
    queryFn: fetchRouterHistory,
    retry: false,
  })
}

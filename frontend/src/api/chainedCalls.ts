// Built with Spec4 AI - https://spec4.ai
/**
 * Typed client for the chained-calls endpoints.
 *
 * Mirrors `singleCall.ts` in shape, including its error messages: `fetch`
 * rejects identically for "the backend isn't running" and "the browser blocked
 * the response for CORS", so the unreachable message names both rather than
 * saying something unactionable.
 */

/** How a run ended. `critique_failed` arrives as a 200 — call 1's output is in the body. */
export type ChainStatus = 'complete' | 'critique_failed'

/** Call 1's block. `role` is stamped by the server from the prompt it sent. */
export interface IntermediateOutput {
  role: 'struggling_writer'
  title: string
  text: string
}

/** Call 2's block. */
export interface FinalOutput {
  role: 'harsh_critic'
  text: string
  /**
   * The phrase the critic took from the story. Rendered as the visible evidence
   * that call 2 actually read call 1's output rather than writing generic
   * commentary that would fit any story.
   */
  quoted_detail: string
}

/**
 * The backend's automated check on that quoted detail.
 *
 * A signal, not a verdict: it establishes the detail is *present* in the story,
 * and establishes nothing about whether the critique is apt. The UI must say
 * which of the two it is — this project's recurring defect is a surface
 * asserting something nothing verified.
 */
export interface QualitySignal {
  quoted_detail_found: boolean
  match_ratio: number
  references_story: boolean
}

/** One completed run of the chain, complete or partial. */
export interface ChainResult {
  status: ChainStatus
  intermediate_output: IntermediateOutput
  final_output: FinalOutput | null
  quality_signal: QualitySignal | null
  /** Plain-language explanation of a partial result. */
  notice: string | null
  /** The slug that served call 1, read off its response. */
  writer_model: string
  critic_model: string | null
}

/** One declared step of the chain, described before it runs. */
export interface ChainStep {
  position: number
  role: string
  label: string
  description: string
}

/** Response body of GET /api/chained-calls/plan. */
export interface ChainPlan {
  steps: ChainStep[]
  chain_length: number
  length_note: string
}

/**
 * What the screen shows when the plan hasn't loaded (or can't).
 *
 * The feature requires the visitor be told each call's job **before**
 * submitting, and this deployment's backend sleeps after ~15 minutes idle — so
 * a first-time visitor routinely arrives before the API answers. Rendering
 * nothing until it does would fail that criterion at exactly the moment it
 * matters most. The server's plan replaces this as soon as it arrives; both are
 * built from the same fixed role constants, and `chained-calls.test.tsx` pins
 * that these roles match the wire types.
 */
export const FALLBACK_PLAN: ChainPlan = {
  steps: [
    {
      position: 1,
      role: 'struggling_writer',
      label: 'Struggling Writer',
      description:
        'Takes your story idea and drafts a short story in a self-doubting, hedging voice. ' +
        'Its output is the only thing the second call sees.',
    },
    {
      position: 2,
      role: 'harsh_critic',
      label: 'Harsh Critic',
      description:
        'Receives that exact draft as its input and critiques it bluntly, quoting a specific ' +
        'detail from it.',
    },
  ],
  chain_length: 2,
  length_note:
    'This demo runs exactly 2 chained calls per submission to conserve a shared ' +
    'budget. The pattern itself supports chains of any length -- two is this demo’s budget, ' +
    'not the pattern’s limit.',
}

/** Mirrors `service.MAX_STORY_PROMPT_CHARS`, so an over-long idea is caught before a round trip. */
export const MAX_STORY_PROMPT_CHARS = 600

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/**
 * A failure the backend described, carrying its machine-readable code.
 *
 * The code separates a spent daily budget (`usage_limit_reached`, which resets
 * at 00:00 UTC and cannot be retried into working) from an unreachable provider
 * (`generation_unavailable`, which can), without matching on prose.
 */
export class ChainedCallsRequestError extends Error {
  readonly code: string
  readonly status: number

  constructor(message: string, code: string, status: number, cause?: unknown) {
    super(message, { cause })
    this.name = 'ChainedCallsRequestError'
    this.code = code
    this.status = status
  }
}

/** Pull a message and code out of an error response, tolerating FastAPI's own 422 shape. */
function errorFrom(body: unknown, status: number): ChainedCallsRequestError {
  if (typeof body === 'object' && body !== null) {
    const record = body as { detail?: unknown; code?: unknown }
    const code = typeof record.code === 'string' ? record.code : 'request_failed'

    if (typeof record.detail === 'string') {
      return new ChainedCallsRequestError(record.detail, code, status)
    }
    if (Array.isArray(record.detail)) {
      const first = record.detail[0] as { msg?: string } | undefined
      if (first?.msg) {
        return new ChainedCallsRequestError(
          first.msg.replace(/^Value error,\s*/, ''),
          'invalid_request',
          status,
        )
      }
    }
  }
  return new ChainedCallsRequestError(`The backend returned ${status}.`, 'request_failed', status)
}

function unreachable(cause: unknown): ChainedCallsRequestError {
  return new ChainedCallsRequestError(
    `Could not reach the backend at ${API_BASE_URL}. Either it isn't running, ` +
      `or this page's origin (${window.location.origin}) doesn't match the ` +
      `backend's CORS_ORIGIN setting.`,
    'unreachable',
    0,
    cause,
  )
}

/**
 * Fetch the description of both calls, to show before anything runs.
 *
 * @returns The two steps, the fixed chain length, and why the length is fixed.
 * @throws ChainedCallsRequestError if the request cannot be made, is blocked, or returns non-2xx.
 */
export async function fetchChainPlan(): Promise<ChainPlan> {
  const url = `${API_BASE_URL}/api/chained-calls/plan`

  let response: Response
  try {
    response = await fetch(url)
  } catch (cause) {
    throw unreachable(cause)
  }

  if (!response.ok) {
    throw new ChainedCallsRequestError(
      `The backend returned ${response.status} for ${url}.`,
      'request_failed',
      response.status,
    )
  }

  return (await response.json()) as ChainPlan
}

export interface ChainSubmission {
  storyPrompt: string
}

/**
 * Run the whole chain: write a story, then critique that exact story.
 *
 * @param submission - The visitor's story idea.
 * @returns Both labeled blocks, or the intermediate one with `critique_failed`.
 * @throws ChainedCallsRequestError if the request cannot be made, is blocked, or is rejected.
 */
export async function runChain({ storyPrompt }: ChainSubmission): Promise<ChainResult> {
  return post(`${API_BASE_URL}/api/chained-calls/generate`, { story_prompt: storyPrompt })
}

export interface CritiqueRetrySubmission {
  /** The story from the failed run, sent back unchanged so the critique matches what's on screen. */
  intermediateOutput: IntermediateOutput
}

/**
 * Re-run only call 2, against a story that already exists.
 *
 * The story travels back through the client because the server stores nothing —
 * that is the capability's privacy requirement, and this is its cost. Sending
 * the draft unchanged is also what makes the retry meaningful: regenerating it
 * would produce a *different* story, so the critique that finally arrived would
 * not be a critique of the draft the visitor is reading.
 *
 * @param submission - The intermediate output from the failed run.
 * @returns The same result shape, now hopefully complete.
 * @throws ChainedCallsRequestError if the request cannot be made, is blocked, or is rejected.
 */
export async function retryCritique({
  intermediateOutput,
}: CritiqueRetrySubmission): Promise<ChainResult> {
  return post(`${API_BASE_URL}/api/chained-calls/retry-critique`, {
    intermediate_output: {
      role: intermediateOutput.role,
      title: intermediateOutput.title,
      text: intermediateOutput.text,
    },
  })
}

/** Shared POST plumbing for both endpoints, which return the same body shape. */
async function post(url: string, payload: unknown): Promise<ChainResult> {
  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } catch (cause) {
    throw unreachable(cause)
  }

  const body: unknown = await response.json().catch(() => null)

  if (!response.ok) {
    throw errorFrom(body, response.status)
  }

  return body as ChainResult
}

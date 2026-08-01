// Built with Spec4 AI - https://spec4.ai
/**
 * The two modes the capability declares.
 *
 * Note the naming: the wire value is `plain`, while the UI labels it "Simple"
 * because that is what the design mock's toggle says. The wire value is used
 * as the client's own state so there is no mapping layer to get wrong.
 */
export type SingleCallMode = 'plain' | 'structured'

/** A JSON Schema as the backend renders it. Opaque to the client, which only displays it. */
export type JsonSchema = Record<string, unknown>

/** The request as the server actually sent it, for the side-by-side display. */
export interface StructuredRequestSent {
  system_prompt: string
  prompt_text: string
  response_schema: JsonSchema
  schema_name: string
}

/**
 * What one single call produced.
 *
 * `schema_conforming` is three-valued on purpose, mirroring the backend:
 * `null` means no schema check was performed (every plain-mode response),
 * `false` means one ran and the response failed it. Collapsing the two would
 * make a plain answer look like a validation failure.
 */
export interface SingleCallResult {
  mode: SingleCallMode
  plain_text: string | null
  structured_object: Record<string, unknown> | null
  schema_conforming: boolean | null
  /** The chain slug that actually served the request, read off the response. */
  model: string
  /** The prompt as the server received it, echoed back. */
  prompt_text: string
  /** The model's unparsed text, present only when a structured response failed validation. */
  raw_output: string | null
  /** Why validation failed, in readable form. */
  validation_error: string | null
  /** What was sent, present for structured calls. */
  structured_request: StructuredRequestSent | null
}

/** One curated preset prompt, offered as a one-click choice. */
export interface PresetPrompt {
  id: string
  label: string
  /** "Summarize" / "Classify" / "Extract" — what the preset demonstrates. */
  intent: string
  /**
   * The complete prompt this preset sends, untruncated. Shown to the visitor
   * before submission, which is the capability's own mitigation for "user is
   * unsure what a preset will produce" — a preview could not satisfy it.
   */
  prompt_text: string
  response_schema: JsonSchema
}

/** Response body of GET /api/single-call/presets. */
export interface SingleCallPresets {
  presets: PresetPrompt[]
  preset_set_version: string
  /** The schema free-text structured prompts are held to. */
  default_response_schema: JsonSchema
}

/** Mirrors `service.MAX_PROMPT_CHARS`, so an over-long prompt is caught before a round trip. */
export const MAX_PROMPT_CHARS = 4000

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/**
 * A failure the backend described, carrying its machine-readable code.
 *
 * The code is what lets the UI distinguish a spent hourly cap (which resets)
 * from an unreachable provider (which does not) without matching on prose.
 */
export class SingleCallRequestError extends Error {
  readonly code: string
  readonly status: number

  constructor(message: string, code: string, status: number, cause?: unknown) {
    super(message, { cause })
    this.name = 'SingleCallRequestError'
    this.code = code
    this.status = status
  }
}

/**
 * Pull a human-readable message and code out of an error response.
 *
 * Two shapes arrive here: this route's own `{status, code, detail}`, and
 * FastAPI's request-validation `{detail: [{msg, loc}]}` when the body fails
 * schema validation before the handler runs.
 */
function errorFrom(body: unknown, status: number): SingleCallRequestError {
  if (typeof body === 'object' && body !== null) {
    const record = body as { detail?: unknown; code?: unknown }
    const code = typeof record.code === 'string' ? record.code : 'request_failed'

    if (typeof record.detail === 'string') {
      return new SingleCallRequestError(record.detail, code, status)
    }
    if (Array.isArray(record.detail)) {
      const first = record.detail[0] as { msg?: string } | undefined
      if (first?.msg) {
        // Pydantic prefixes validator failures with "Value error, ".
        return new SingleCallRequestError(
          first.msg.replace(/^Value error,\s*/, ''),
          'invalid_request',
          status,
        )
      }
    }
  }
  return new SingleCallRequestError(`The backend returned ${status}.`, 'request_failed', status)
}

function unreachable(cause: unknown): SingleCallRequestError {
  return new SingleCallRequestError(
    `Could not reach the backend at ${API_BASE_URL}. Either it isn't running, ` +
      `or this page's origin (${window.location.origin}) doesn't match the ` +
      `backend's CORS_ORIGIN setting.`,
    'unreachable',
    0,
    cause,
  )
}

/**
 * Fetch the curated preset prompts and the default structured schema.
 *
 * @returns The preset set, its version, and the default response schema.
 * @throws SingleCallRequestError if the request cannot be made, is blocked, or returns non-2xx.
 */
export async function fetchSingleCallPresets(): Promise<SingleCallPresets> {
  const url = `${API_BASE_URL}/api/single-call/presets`

  let response: Response
  try {
    response = await fetch(url)
  } catch (cause) {
    throw unreachable(cause)
  }

  if (!response.ok) {
    throw new SingleCallRequestError(
      `The backend returned ${response.status} for ${url}.`,
      'request_failed',
      response.status,
    )
  }

  return (await response.json()) as SingleCallPresets
}

export interface SingleCallSubmission {
  /** The prompt as typed. Sent only when no preset is selected. */
  promptText: string
  /**
   * The selected preset, if any. When present the server sends that preset's
   * canonical text, which is also what the textarea is showing — so the two
   * cannot diverge. Editing the text clears this, making it a free-text
   * submission.
   */
  presetPromptId?: string | null
  mode: SingleCallMode
}

/**
 * Run one single call against the backend.
 *
 * `fetch` rejects identically for "the backend isn't running" and "the browser
 * blocked the response for CORS" — the browser withholds the difference
 * deliberately. Since the backend pins `CORS_ORIGIN` to exactly one origin,
 * opening the app on a different host or port produces a server-side 200 the
 * browser still discards, so the message names both possibilities rather than
 * saying something unactionable.
 *
 * @param submission - The prompt or preset, and the requested response mode.
 * @returns The model's response and the model that served it.
 * @throws SingleCallRequestError if the request cannot be made, is blocked, or is rejected.
 */
export async function runSingleCall({
  promptText,
  presetPromptId,
  mode,
}: SingleCallSubmission): Promise<SingleCallResult> {
  const url = `${API_BASE_URL}/api/single-call/generate`

  // Only one prompt source goes on the wire. The server resolves a preset to
  // its own canonical text and ignores free text when both arrive, so sending
  // both would leave the request ambiguous about which one was intended.
  const payload = presetPromptId
    ? { preset_prompt_id: presetPromptId, mode }
    : { prompt_text: promptText, mode }

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

  return body as SingleCallResult
}

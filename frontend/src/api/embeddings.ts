// Built with Spec4 AI - https://spec4.ai
/**
 * One preconfigured TextExample at its position in the shared 2D projection.
 *
 * `x`/`y` come from a PCA fitted once, server-side, over the whole preset
 * set — they are only meaningful relative to each other, and the axes carry
 * no unit. The backend never re-fits, so these coordinates are stable for
 * the life of the process and across reloads.
 */
export interface PresetPoint {
  label: string
  category: string
  x: number
  y: number
}

/** One preset near the submitted custom text, ranked in the unprojected space. */
export interface NearestNeighbor {
  text: string
  distance: number
}

/**
 * Where a visitor's text landed in the presets' existing 2D space.
 *
 * `point` comes from `transform()` on the projection already fitted over the
 * presets — never a re-fit — so adding this point cannot move any preset.
 */
export interface PlacementResult {
  point: { x: number; y: number }
  text: string
  nearest_neighbors: NearestNeighbor[]
  embedding_model_version: string
}

/**
 * Maximum characters accepted, mirroring `placement.MAX_CUSTOM_TEXT_CHARS`.
 *
 * Duplicated rather than fetched: the backend rejects over-long text on its
 * own, and this only exists so the visitor is told before a pointless round
 * trip. If the backend's bound changes, this becomes merely conservative
 * rather than wrong.
 */
export const MAX_CUSTOM_TEXT_CHARS = 500

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/**
 * Fetch the curated preset examples and their projected coordinates.
 *
 * The two failure modes are reported differently on purpose. `fetch` rejects
 * with a TypeError for *both* "the backend isn't running" and "the browser
 * blocked the response for CORS", and the two are indistinguishable from
 * script — the browser withholds the detail deliberately. Since the backend
 * pins `CORS_ORIGIN` to exactly one origin, opening the app on a different
 * host or port than that value produces a server-side 200 that the browser
 * still discards, so the message names both possibilities and the URL that
 * was actually attempted rather than saying something vague.
 *
 * @returns Every preset, each with its category and (x, y) position.
 * @throws Error if the request cannot be made, is blocked, or returns non-2xx.
 */
export async function fetchPresets(): Promise<PresetPoint[]> {
  const url = `${API_BASE_URL}/api/embeddings/presets`

  let response: Response
  try {
    response = await fetch(url)
  } catch (cause) {
    throw new Error(
      `Could not reach the backend at ${API_BASE_URL}. Either it isn't running, ` +
        `or this page's origin (${window.location.origin}) doesn't match the ` +
        `backend's CORS_ORIGIN setting.`,
      { cause },
    )
  }

  if (!response.ok) {
    throw new Error(`The backend returned ${response.status} for ${url}.`)
  }

  const body = (await response.json()) as { presets: PresetPoint[] }
  return body.presets
}

/**
 * Pull a human-readable message out of an error response.
 *
 * Two shapes arrive here. The placement route returns its own
 * `{status, code, detail}` for failures it raises, while FastAPI's request
 * validation returns `{detail: [{msg, loc}, ...]}` before the handler runs.
 * Client-side validation normally prevents the second, but a malformed body
 * from anywhere else should still read as a sentence rather than `[object
 * Object]`.
 */
function errorMessageFrom(body: unknown, status: number): string {
  if (typeof body === 'object' && body !== null) {
    const detail = (body as { detail?: unknown }).detail

    if (typeof detail === 'string') {
      return detail
    }
    if (Array.isArray(detail)) {
      const first = detail[0] as { msg?: string } | undefined
      if (first?.msg) {
        // Pydantic prefixes validator failures with "Value error, ".
        return first.msg.replace(/^Value error,\s*/, '')
      }
    }
  }
  return `The backend returned ${status}.`
}

/**
 * Place a visitor's custom text on the presets' existing 2D plot.
 *
 * The text is not persisted anywhere — the backend holds it for the duration
 * of the request only and never logs it verbatim.
 *
 * @param customText - The visitor's word, phrase, or sentence.
 * @returns The projected point, its nearest presets, and the model version.
 * @throws Error if the request cannot be made, is blocked, or is rejected.
 */
export async function placeCustomText(customText: string): Promise<PlacementResult> {
  const url = `${API_BASE_URL}/api/embeddings/place`

  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ custom_text: customText }),
    })
  } catch (cause) {
    throw new Error(
      `Could not reach the backend at ${API_BASE_URL}. Either it isn't running, ` +
        `or this page's origin (${window.location.origin}) doesn't match the ` +
        `backend's CORS_ORIGIN setting.`,
      { cause },
    )
  }

  const body: unknown = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(errorMessageFrom(body, response.status))
  }

  return body as PlacementResult
}

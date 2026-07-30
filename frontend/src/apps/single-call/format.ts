// Built with Spec4 AI - https://spec4.ai
import type { JsonSchema, StructuredRequestSent } from '../../api/singleCall'

/**
 * Pure display helpers for the single-call screen.
 *
 * Separate from the components for the same reason `apps/embeddings/plotTraces.ts`
 * is: a module that exports both components and plain functions defeats React's
 * fast refresh, and these are worth unit-testing without rendering anything.
 */

/**
 * Read a schema's display name off its JSON Schema `title`.
 *
 * The backend emits `title` from the Pydantic model's class name, so this is
 * the schema's real identity rather than a label invented here — the same
 * string the request resolves against server-side.
 *
 * @param schema - A JSON Schema object from the backend, or nothing.
 * @returns The title, or null when the schema carries none.
 */
export function schemaTitleOf(schema: JsonSchema | null | undefined): string | null {
  const title = schema?.title
  return typeof title === 'string' ? title : null
}

/**
 * Render the request pane's JSON for the side-by-side structured display.
 *
 * Built from the server's own record of what it sent, so the two panes are
 * genuinely a request and its response rather than the client's intent beside
 * someone else's answer. The system prompt is deliberately not included: it
 * restates the whole schema and would push the schema itself out of view, so
 * the component discloses it separately.
 *
 * @param request - The structured request the server reported sending.
 * @returns Pretty-printed JSON for the `<pre>` block.
 */
export function formatRequest(request: StructuredRequestSent): string {
  return JSON.stringify(
    {
      mode: 'structured',
      prompt: request.prompt_text,
      response_schema: request.response_schema,
    },
    null,
    2,
  )
}

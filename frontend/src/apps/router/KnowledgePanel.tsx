// Built with Spec4 AI - https://spec4.ai
import type { RouterRoute, RouteId } from '../../api/router'

/** Props for {@link KnowledgePanel}. */
export interface KnowledgePanelProps {
  /** The exact string the router prompt receives. Rendered verbatim. */
  block: string
  /** Server-side SHA-256 of `block`. */
  sha256: string
  routes: RouterRoute[]
  decisionMargin: number
  costOrder: RouteId[]
}

/**
 * `Router Knowledge Panel`: exactly what the router was told.
 *
 * The block is rendered in a `<pre>` with no trimming, no wrapping into
 * paragraphs and no markdown, because the page's claim is that this text is
 * byte for byte what the router received. Any processing here — even
 * collapsing whitespace — would make that claim false while looking identical.
 * The hash beside it is the server's, so the claim can be checked.
 *
 * The decision margin and the cost order are printed beside the descriptions
 * because they are the other half of what decides a run.
 */
export function KnowledgePanel({
  block,
  sha256,
  routes,
  decisionMargin,
  costOrder,
}: KnowledgePanelProps) {
  const labelFor = (id: RouteId) => routes.find((route) => route.id === id)?.label ?? id

  return (
    <section
      aria-label="Router knowledge panel"
      className="rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-800 dark:bg-gray-900"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-mono text-xs uppercase tracking-wide text-gray-500">
          Router knowledge panel
        </h2>
        <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-semibold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
          exactly what the router was told
        </span>
      </div>
      <pre
        data-testid="route-descriptions-block"
        className="mt-3 overflow-x-auto whitespace-pre-wrap break-words rounded-lg bg-gray-50 p-3 font-mono text-xs leading-relaxed text-gray-800 dark:bg-gray-950 dark:text-gray-200"
      >
        {block}
      </pre>
      <p className="mt-1 font-mono text-[11px] text-gray-500">
        sha256 <span data-testid="route-descriptions-sha256">{sha256}</span>
      </p>
      <dl className="mt-3 grid gap-1 text-sm text-gray-700 dark:text-gray-300">
        <div>
          <dt className="inline font-semibold">Decision margin: </dt>
          <dd className="inline">
            <code data-testid="decision-margin">{decisionMargin}</code> — if the top two scores are
            within this, the run is low-confidence and goes to the cheaper of the two.
          </dd>
        </div>
        <div>
          <dt className="inline font-semibold">Cost order: </dt>
          <dd className="inline" data-testid="cost-order">
            {costOrder.map(labelFor).join(' < ')}
          </dd>
        </div>
      </dl>
    </section>
  )
}

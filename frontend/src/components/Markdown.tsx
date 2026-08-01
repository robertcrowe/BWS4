// Built with Spec4 AI - https://spec4.ai
import ReactMarkdown from 'react-markdown'

/**
 * The shared renderer for model-written markdown.
 *
 * **This exists so that `dangerouslySetInnerHTML` never appears anywhere near
 * model output.** Every surface that shows generated prose is public,
 * unauthenticated, and — on the orchestrated screen — derived from free-form
 * text a visitor typed. Rendering that through `innerHTML` would be a genuine
 * stored-XSS path: the visitor's own words travel to a model and come back as
 * a merged answer on the page. `react-markdown` parses to React elements, so
 * raw HTML in the source is text rather than markup, and no plugin here
 * re-enables it (`rehype-raw` is exactly what must never be added).
 *
 * `remark-gfm` is deliberately absent. The stack marks it optional, and tables
 * and strikethrough are not worth a dependency on a surface whose job is
 * prose.
 *
 * Styling is explicit per element rather than a `prose` class, because
 * `@tailwindcss/typography` is not installed and adding a plugin to style four
 * element types would be the larger change. Every colour is written as a
 * light/dark pair, as the project's theming requires.
 *
 * ## Why paragraphs keep `whitespace-pre-wrap`
 *
 * Only two of this component's callers are given prose a prompt actually asked
 * to be markdown; the rest render output from prompts that say nothing about
 * formatting (RAG, single call, chained calls) or that explicitly forbid it
 * (the tool-use agent, which models disregard often enough to be worth
 * handling). Markdown collapses a *single* newline into a space, so on that
 * output — a haiku, a stanza, lines a model chose to break itself — plain
 * rendering would silently reflow text that `whitespace-pre-wrap` used to lay
 * out correctly.
 *
 * A soft break survives into the DOM as a literal `\n` inside the paragraph's
 * text node, so `pre-wrap` restores it while markdown structure still parses
 * above it. That is what makes this renderer safe to point at output that is
 * not markdown at all, which is the case on most of these screens. It is also
 * why `remark-breaks` is not a dependency: CSS already does the job.
 */

/**
 * How prominent the rendered prose is.
 *
 * `lead` is the answer a visitor came for — the RAG and tool-use screens each
 * have exactly one. `default` is everything else: a step's output, a column, a
 * merge. Two variants rather than free-form classes because the distinction is
 * about a surface's role, and the alternative is five screens drifting apart on
 * body text.
 */
export type MarkdownVariant = 'default' | 'lead'

/** Renders one block of model-written markdown as React elements. */
export interface MarkdownProps {
  /** The markdown source. Untrusted: treated as content, never as markup. */
  children: string
  /** Extra classes for the wrapper. */
  className?: string
  /** Prominence of the body text. Defaults to `default`. */
  variant?: MarkdownVariant
}

const BODY_CLASSES: Record<MarkdownVariant, string> = {
  default: 'text-sm leading-relaxed text-gray-700 dark:text-gray-300',
  lead: 'text-[15px] leading-relaxed text-gray-900 dark:text-gray-100',
}

function componentsFor(variant: MarkdownVariant) {
  // See the note above: `pre-wrap` is what keeps a model's own line breaks.
  const body = `whitespace-pre-wrap ${BODY_CLASSES[variant]}`

  return {
    h1: (props: { children?: React.ReactNode }) => (
      <h3 className="mt-4 mb-2 text-base font-semibold text-gray-900 first:mt-0 dark:text-gray-100">
        {props.children}
      </h3>
    ),
    h2: (props: { children?: React.ReactNode }) => (
      <h4 className="mt-4 mb-2 text-sm font-semibold text-gray-900 first:mt-0 dark:text-gray-100">
        {props.children}
      </h4>
    ),
    h3: (props: { children?: React.ReactNode }) => (
      <h5 className="mt-3 mb-1.5 text-sm font-semibold text-gray-800 first:mt-0 dark:text-gray-200">
        {props.children}
      </h5>
    ),
    p: (props: { children?: React.ReactNode }) => (
      <p className={`mb-3 last:mb-0 ${body}`}>{props.children}</p>
    ),
    ul: (props: { children?: React.ReactNode }) => (
      <ul className="mb-3 ml-5 list-disc space-y-1 last:mb-0">{props.children}</ul>
    ),
    ol: (props: { children?: React.ReactNode }) => (
      <ol className="mb-3 ml-5 list-decimal space-y-1 last:mb-0">{props.children}</ol>
    ),
    li: (props: { children?: React.ReactNode }) => (
      <li className={body}>{props.children}</li>
    ),
    blockquote: (props: { children?: React.ReactNode }) => (
      <blockquote className="mb-3 border-l-2 border-gray-300 pl-3 italic last:mb-0 dark:border-gray-700">
        {props.children}
      </blockquote>
    ),
    strong: (props: { children?: React.ReactNode }) => (
      <strong className="font-semibold text-gray-900 dark:text-gray-100">
        {props.children}
      </strong>
    ),
    code: (props: { children?: React.ReactNode }) => (
      <code className="rounded bg-gray-100 px-1 py-0.5 font-mono text-xs text-gray-800 dark:bg-gray-800 dark:text-gray-200">
        {props.children}
      </code>
    ),
    a: (props: { children?: React.ReactNode; href?: string }) => (
      // No `href` is passed through. A link in model output points wherever the
      // model decided, which on an unauthenticated public page is not something
      // to hand a visitor a click on.
      <span className="text-violet-700 underline dark:text-violet-300">{props.children}</span>
    ),
  }
}

//: Built once per variant at module load, so `ReactMarkdown` is not handed a
//: fresh component map on every render.
const COMPONENTS: Record<MarkdownVariant, ReturnType<typeof componentsFor>> = {
  default: componentsFor('default'),
  lead: componentsFor('lead'),
}

/**
 * Render model-written markdown safely.
 *
 * @param props - The markdown source, prominence variant, and wrapper classes.
 * @returns The parsed markdown as React elements.
 */
export function Markdown({ children, className, variant = 'default' }: MarkdownProps) {
  return (
    <div className={className}>
      <ReactMarkdown components={COMPONENTS[variant]}>{children}</ReactMarkdown>
    </div>
  )
}

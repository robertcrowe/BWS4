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
 */

/** Renders one block of model-written markdown as React elements. */
export interface MarkdownProps {
  /** The markdown source. Untrusted: treated as content, never as markup. */
  children: string
  /** Extra classes for the wrapper. */
  className?: string
}

const COMPONENTS = {
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
    <p className="mb-3 text-sm leading-relaxed text-gray-700 last:mb-0 dark:text-gray-300">
      {props.children}
    </p>
  ),
  ul: (props: { children?: React.ReactNode }) => (
    <ul className="mb-3 ml-5 list-disc space-y-1 last:mb-0">{props.children}</ul>
  ),
  ol: (props: { children?: React.ReactNode }) => (
    <ol className="mb-3 ml-5 list-decimal space-y-1 last:mb-0">{props.children}</ol>
  ),
  li: (props: { children?: React.ReactNode }) => (
    <li className="text-sm leading-relaxed text-gray-700 dark:text-gray-300">
      {props.children}
    </li>
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

/**
 * Render model-written markdown safely.
 *
 * @param props - The markdown source and optional wrapper classes.
 * @returns The parsed markdown as React elements.
 */
export function Markdown({ children, className }: MarkdownProps) {
  return (
    <div className={className}>
      <ReactMarkdown components={COMPONENTS}>{children}</ReactMarkdown>
    </div>
  )
}

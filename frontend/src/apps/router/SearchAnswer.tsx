// Built with Spec4 AI - https://spec4.ai
import type { AnswerEvent } from '../../api/router'
import { Markdown } from '../../components/Markdown'

/**
 * Exa's ISO date as a short date, or "undated" — an empty slot reads as
 * "recent", and relevance is not recency.
 */
function formatPublished(published: string | null): string {
  if (!published) {
    return 'undated'
  }
  const parsed = new Date(published)
  return Number.isNaN(parsed.getTime()) ? 'undated' : parsed.toISOString().slice(0, 10)
}

/**
 * The search route's answer in the Tool Use example's layout: the exact query,
 * the answer, and the sources beside it so every `[n]` resolves.
 *
 * Router-local because the Tool Use app's answer panel is private to its
 * module; this mirrors its layout rather than editing that app to export it.
 * The one deliberate difference: the query line says *code* chose to search,
 * because here no model decided — the router had already stopped.
 */
export function SearchAnswer({ answer }: { answer: AnswerEvent }) {
  return (
    <div data-testid="search-answer" className="grid gap-3">
      {answer.query && (
        <p className="font-mono text-xs text-blue-600 dark:text-blue-400">
          ↳ one search, issued by code with the request as the query: &quot;{answer.query}&quot;
        </p>
      )}
      {answer.text && <Markdown variant="lead">{answer.text}</Markdown>}
      <CitationWarnings answer={answer} />
      {answer.snippets.length > 0 && (
        <div>
          <h5 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Sources the answer may cite
          </h5>
          <ol className="grid gap-2" aria-label="Search sources">
            {answer.snippets.map((snippet) => (
              <li
                key={snippet.index}
                className="rounded-lg border border-gray-200 bg-gray-100 p-3 dark:border-gray-800 dark:bg-gray-800/40"
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <strong className="text-[13px] text-gray-900 dark:text-gray-100">
                    [{snippet.index}] {snippet.title}
                  </strong>
                  <span className="shrink-0 font-mono text-[11px] text-gray-500">
                    {formatPublished(snippet.published_date)}
                  </span>
                </div>
                <p className="mb-1 text-xs text-gray-600 dark:text-gray-400">{snippet.excerpt}</p>
                <a
                  href={snippet.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="break-all font-mono text-[11px] text-indigo-600 underline dark:text-indigo-300"
                >
                  {snippet.url}
                </a>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

/** Shown when the server stripped citations or links the sources don't back. */
export function CitationWarnings({ answer }: { answer: AnswerEvent }) {
  if (answer.invalid_citations.length === 0 && answer.removed_urls.length === 0) {
    return null
  }
  return (
    <p
      data-testid="citation-warning"
      className="rounded-lg border border-red-500/35 bg-red-500/10 p-3 text-xs text-red-600 dark:text-red-400"
    >
      {answer.invalid_citations.length > 0 &&
        `The answer cited ${answer.invalid_citations.map((n) => `[${n}]`).join(', ')}, which match no source; ${answer.invalid_citations.length === 1 ? 'that citation was' : 'those citations were'} removed. `}
      {answer.removed_urls.length > 0 &&
        `${answer.removed_urls.length} link${answer.removed_urls.length === 1 ? '' : 's'} not among the sources ${answer.removed_urls.length === 1 ? 'was' : 'were'} removed.`}
    </p>
  )
}

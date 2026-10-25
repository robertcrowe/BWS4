// Built with Spec4 AI - https://spec4.ai
import type { AnswerEvent } from '../../api/router'
import { Markdown } from '../../components/Markdown'
import { CitationWarnings } from './SearchAnswer'

/**
 * The retrieval route's answer in the RAG example's layout: the answer, the
 * grounding verdict, and the retrieved passages — title, excerpt, similarity —
 * with the cited ones marked.
 *
 * Router-local because the RAG app's answer card is private to its module;
 * this mirrors its layout rather than editing that app to export it.
 */
export function RetrievalAnswer({ answer }: { answer: AnswerEvent }) {
  return (
    <div data-testid="retrieval-answer" className="grid gap-3">
      {answer.grounding === 'unsupported' && (
        <p className="rounded-lg border border-amber-500/35 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
          Retrieval found passages that looked relevant, but the answer cites none of them, so it is
          shown ungrounded rather than dressed up as a cited one.
        </p>
      )}
      {answer.text && <Markdown variant="lead">{answer.text}</Markdown>}
      <CitationWarnings answer={answer} />
      <PassageList answer={answer} />
    </div>
  )
}

/** The retrieved passages, ranked, with similarity and whether each was cited. */
export function PassageList({ answer }: { answer: AnswerEvent }) {
  if (answer.passages.length === 0) {
    return null
  }
  return (
    <div>
      <h5 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
        Retrieved passages
      </h5>
      <ol className="grid gap-2" aria-label="Retrieved passages">
        {answer.passages.map((passage) => (
          <li
            key={passage.index}
            className={`rounded-lg border bg-gray-100 p-3 dark:bg-gray-800/40 ${
              passage.cited
                ? 'border-emerald-500/40'
                : 'border-gray-200 opacity-70 dark:border-gray-800'
            }`}
          >
            <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
              <strong className="text-[13px] text-gray-900 dark:text-gray-100">
                [{passage.index}] {passage.title}
              </strong>
              <span className="flex items-center gap-2 font-mono text-[11px] text-gray-500">
                <span>{passage.cited ? 'cited' : 'retrieved, not cited'}</span>
                <span>similarity {passage.similarity.toFixed(2)}</span>
              </span>
            </div>
            <p className="text-xs text-gray-600 dark:text-gray-400">{passage.excerpt}</p>
          </li>
        ))}
      </ol>
    </div>
  )
}

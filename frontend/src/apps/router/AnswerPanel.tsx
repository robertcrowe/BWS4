// Built with Spec4 AI - https://spec4.ai
import type { AnswerEvent, RouteId } from '../../api/router'
import { Markdown } from '../../components/Markdown'
import { DeterministicResult } from './DeterministicResult'
import { PassageList, RetrievalAnswer } from './RetrievalAnswer'
import { SearchAnswer } from './SearchAnswer'
import { SingleCallAnswer } from './SingleCallAnswer'

/** Props for {@link AnswerPanel}. */
export interface AnswerPanelProps {
  answer: AnswerEvent
  labelFor: (route: RouteId) => string
}

/**
 * The dispatched route's answer, labelled with the path that produced it, in
 * that route's own layout: the evaluator's verdict for the deterministic route,
 * the Single Call example's result card, the RAG example's passages, or the
 * Tool Use example's sources.
 *
 * A failure is shown as a failure and a notice as a notice — with whatever the
 * route did gather (snippets, passages) still listed. Nothing stands in for an
 * answer that was not produced.
 */
export function AnswerPanel({ answer, labelFor }: AnswerPanelProps) {
  return (
    <div className="grid gap-2" data-testid="answer-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-mono text-xs uppercase tracking-wide text-gray-500">Answer</h4>
        <span
          data-testid="answer-route"
          className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-semibold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
        >
          via {labelFor(answer.route)}
        </span>
      </div>
      {answer.answer_kind === 'failure' && (
        <p
          role="alert"
          data-testid="answer-error"
          className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
        >
          {answer.error}
        </p>
      )}
      {answer.answer_kind === 'notice' && (
        <p
          data-testid="answer-notice"
          className="rounded-lg border border-amber-500/35 bg-amber-500/10 px-3 py-2 text-sm text-amber-800 dark:text-amber-300"
        >
          {answer.error}
        </p>
      )}
      {answer.answer_kind === 'deterministic' && <DeterministicResult answer={answer} />}
      {answer.answer_kind === 'text' && <TextAnswerView answer={answer} />}
      {answer.answer_kind !== 'text' && answer.route === 'search_generation' && (
        <SearchAnswer answer={answer} />
      )}
      {answer.answer_kind !== 'text' && answer.route === 'retrieval' && (
        <PassageList answer={answer} />
      )}
      {answer.truncated && (
        <p className="text-xs text-gray-500">The answer was cut at a sentence to fit the card.</p>
      )}
    </div>
  )
}

/** A generated answer, in the layout of the example app its route belongs to. */
function TextAnswerView({ answer }: { answer: AnswerEvent }) {
  switch (answer.route) {
    case 'single_call':
      return <SingleCallAnswer answer={answer} />
    case 'retrieval':
      return <RetrievalAnswer answer={answer} />
    case 'search_generation':
      return <SearchAnswer answer={answer} />
    default:
      return <Markdown>{answer.text ?? ''}</Markdown>
  }
}

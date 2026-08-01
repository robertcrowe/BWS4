// Built with Spec4 AI - https://spec4.ai
import { type FormEvent, useState } from 'react'

import type { AskRagResponse } from '../../api/rag'
import { useAskRagMutation } from '../../api/useRag'
import { Markdown } from '../../components/Markdown'

// The last two are deliberately unanswerable, in the two different ways this
// demo distinguishes: the pizza question is rejected by the retriever before
// any model runs, while the first-woman question sails past the similarity
// threshold on the dataset's Gagarin passages and has to be caught by the
// citation audit instead.
const EXAMPLE_QUESTIONS = [
  'When did Voyager 1 launch and what is it doing now?',
  'What did the Apollo 11 mission accomplish?',
  'What does the James Webb Space Telescope observe?',
  'Who was the first woman in space?',
  "What's the best pizza topping?",
]

/**
 * rag_question_answer surface: lets a visitor ask a question and see the
 * generated answer alongside the specific retrieved passages that grounded
 * it, so the retrieval-to-generation chain stays visible.
 */
export function QuestionAnswer() {
  const [question, setQuestion] = useState('')
  const mutation = useAskRagMutation()

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = question.trim()
    if (!trimmed) {
      return
    }
    mutation.mutate(trimmed)
  }

  return (
    <div>
      <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
        <h4 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">Ask a question</h4>

        <div className="mb-4 flex flex-wrap gap-2">
          {EXAMPLE_QUESTIONS.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setQuestion(example)}
              className="rounded-full border border-gray-200 dark:border-gray-800 px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400 hover:border-violet-500 hover:text-gray-800 dark:hover:text-gray-200"
            >
              {example}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="flex gap-2.5">
          <input
            type="text"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="e.g. When did Voyager 1 launch and what is it doing now?"
            className="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 px-4 py-3 text-sm text-gray-900 dark:text-gray-100 focus:border-violet-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={mutation.isPending}
            className="rounded-lg bg-violet-500 px-5 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            Ask
          </button>
        </form>
      </div>

      <div className="mt-5">
        {mutation.isPending && (
          <p className="font-mono text-xs text-gray-500">Retrieving passages and generating an answer…</p>
        )}

        {mutation.isError && (
          <div role="alert" className="rounded-2xl border border-red-500/40 bg-white dark:bg-gray-900 p-5">
            <span className="mb-2 inline-block rounded-full border border-red-500/40 px-2.5 py-1 text-xs text-red-600 dark:text-red-400">
              Service unavailable
            </span>
            <p className="text-sm text-gray-700 dark:text-gray-300">
              This demonstration is temporarily unavailable — the shared text-generation
              capability could not be reached. Please try again later.
            </p>
          </div>
        )}

        {mutation.isSuccess && <AnswerCard question={question} response={mutation.data} />}
      </div>
    </div>
  )
}

/**
 * The status badge, derived from what the answer actually cited rather than
 * from the retriever's similarity score. Those two are easy to conflate and
 * mean different things: passages can score well above the threshold on a
 * question the dataset cannot answer, and the score is known before the model
 * has written a word.
 */
function StatusBadge({ response }: { response: AskRagResponse }) {
  const styles = {
    grounded: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
    unsupported: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400',
    low_relevance: 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400',
  }[response.status]

  const label = {
    grounded: `Grounded in ${response.cited_passages.length} of ${response.retrieved_passages.length} retrieved passage(s)`,
    unsupported: 'Not grounded · answer cites no retrieved passage',
    low_relevance: 'Low confidence · weak grounding',
  }[response.status]

  return (
    <span className={`rounded-full border px-2.5 py-1 font-mono text-[11.5px] ${styles}`}>
      {label}
    </span>
  )
}

function AnswerCard({
  question,
  response,
}: {
  question: string
  response: AskRagResponse
}) {
  const isFlagged = response.status !== 'grounded'
  const citedPassages = new Set(response.cited_passages)

  return (
    <div
      className={`rounded-2xl border p-5 bg-white dark:bg-gray-900 ${
        isFlagged ? 'border-amber-500/40' : 'border-gray-200 dark:border-gray-800'
      }`}
    >
      <div className="mb-3.5 flex flex-wrap items-center gap-2.5">
        <span className="rounded-full border border-gray-200 dark:border-gray-800 px-2.5 py-1 text-xs text-gray-600 dark:text-gray-400">
          Question: &quot;{question}&quot;
        </span>
        <StatusBadge response={response} />
      </div>

      {response.status === 'low_relevance' && (
        <div className="mb-4 flex gap-2 rounded-lg border border-amber-500/35 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
          <span aria-hidden="true">⚠</span>
          <span>
            Dataset gap detected before generation: no retrieved passage scored above the
            similarity threshold, so no answer was generated at all. Retrieval-augmented answers
            are only as good as the dataset behind them.
          </span>
        </div>
      )}

      {response.status === 'unsupported' && (
        <div className="mb-4 flex gap-2 rounded-lg border border-amber-500/35 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400">
          <span aria-hidden="true">⚠</span>
          <span>
            Retrieval found passages that <em>looked</em> relevant — they scored above the
            similarity threshold — but the model&apos;s answer cites none of them. A similarity
            score measures topical resemblance, not whether the dataset contains the answer, so
            this response is shown ungrounded rather than dressed up as a cited one.
          </span>
        </div>
      )}

      {response.unresolved_citations.length > 0 && (
        <div className="mb-4 flex gap-2 rounded-lg border border-red-500/35 bg-red-500/10 p-3 text-xs text-red-600 dark:text-red-400">
          <span aria-hidden="true">⚠</span>
          <span>
            The answer cites{' '}
            {response.unresolved_citations.map((n) => `[${n}]`).join(', ')}, which
            {response.unresolved_citations.length === 1 ? ' matches' : ' match'} no retrieved
            passage. The citation was invented by the model.
          </span>
        </div>
      )}

      {/* Markdown, not plain text: the prompt asks for prose with bracketed
          citations and says nothing about formatting, so models routinely
          answer with lists and bold. A bare `[1]` has no link definition to
          resolve against, so citation markers still render literally — which
          the passage cards below depend on. */}
      <Markdown className="mb-5" variant="lead">
        {response.answer}
      </Markdown>

      {response.retrieved_passages.length > 0 && (
        <div>
          <h5 className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-gray-500">
            Retrieved passages
          </h5>
          {response.retrieved_passages.map((passage, index) => {
            const wasCited = citedPassages.has(index + 1)
            return (
              <div
                key={passage.passage_id}
                className={`mb-2.5 rounded-lg border bg-gray-100 dark:bg-gray-800/40 p-3.5 ${
                  wasCited
                    ? 'border-emerald-500/40'
                    : 'border-gray-200 dark:border-gray-800 opacity-70'
                }`}
              >
                <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2.5">
                  <strong className="text-[13px] text-gray-900 dark:text-gray-100">
                    [{index + 1}] {passage.source_title}
                  </strong>
                  <span className="flex items-center gap-2">
                    <span
                      className={`rounded-md border px-2 py-0.5 font-mono text-[11px] ${
                        wasCited
                          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                          : 'border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-950 text-gray-500'
                      }`}
                    >
                      {wasCited ? 'cited' : 'retrieved, not cited'}
                    </span>
                    <span className="rounded-md border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-950 px-2 py-0.5 font-mono text-[11px] text-gray-500">
                      match score: {passage.similarity_score.toFixed(2)}
                    </span>
                  </span>
                </div>
                <p className="text-xs text-gray-600 dark:text-gray-400">{passage.text_excerpt}</p>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// Built with Spec4 AI - https://spec4.ai
import type { AnswerEvent } from '../../api/router'

/**
 * The deterministic route's result: the expression, the evaluator's verdict,
 * and the value. No model produced this; the expression the router wrote was
 * parsed by the evaluator and never executed.
 */
export function DeterministicResult({ answer }: { answer: AnswerEvent }) {
  return (
    <div
      data-testid="deterministic-result"
      className="rounded-lg border border-gray-200 p-3 text-sm dark:border-gray-800"
    >
      <p className="text-xs text-gray-500">
        Evaluator verdict:{' '}
        <span className="font-semibold text-emerald-700 dark:text-emerald-400">
          {answer.evaluator_verdict}
        </span>{' '}
        — the expression was parsed by the no-model evaluator; model text is never executed.
      </p>
      <p className="mt-2 font-mono">
        <code data-testid="deterministic-expression">{answer.expression}</code> ={' '}
        <strong data-testid="deterministic-value">{answer.value_display}</strong>
      </p>
      <p className="mt-1 text-xs text-gray-500">No generation call was made.</p>
    </div>
  )
}

// Built with Spec4 AI - https://spec4.ai
import type { AnswerEvent } from '../../api/router'
import type { SingleCallResult } from '../../api/singleCall'
import { SingleCallResultView } from '../single-call/SingleCallResultView'

/**
 * The single-call route's answer, in the Single Call example's own layout.
 *
 * A Router-local adapter: the Single Call app's presentational component is
 * imported unchanged and given the Router's payload as props, so the routed
 * answer looks exactly like that example's plain-mode result — which is the
 * point: the Router dispatches to an existing path, it does not invent one.
 */
export function SingleCallAnswer({ answer }: { answer: AnswerEvent }) {
  const result: SingleCallResult = {
    mode: 'plain',
    plain_text: answer.text,
    structured_object: null,
    schema_conforming: null,
    model: answer.model ?? 'unknown',
    prompt_text: '',
    raw_output: null,
    validation_error: null,
    structured_request: null,
  }
  return <SingleCallResultView result={result} />
}

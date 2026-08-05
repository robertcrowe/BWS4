// Built with Spec4 AI - https://spec4.ai
import { useCallback, useRef, useState } from 'react'

import { MAX_QUESTION_CHARS, ReactRequestError, checkSuitability } from '../../api/react'
import type { QuestionSuitability } from '../../api/react'
import { useReactPresets } from '../../api/useReact'
import { useReactRun } from '../../api/useReactRun'
import { AnnotationPanel } from './AnnotationPanel'
import { PatternOverview } from './PatternOverview'
import { PriorRuns } from './PriorRuns'
import { QuestionForm } from './QuestionForm'
import { AnswerCard, ExhaustedCard, TraceStream } from './TraceStream'
import { SESSION_LIMIT_MESSAGE, SHOWCASE_LIMIT_MESSAGE } from './runAllowance'
import { useRunAllowance } from './useRunAllowance'

/**
 * The ReAct Loop app: choose a question, watch the loop, read one ending.
 *
 * **The exhausted state is an additive disable, not a state transition.** When
 * the two-run allowance is spent the controls are disabled in place and the
 * trace region above is left exactly as it was — the spec requires previous
 * results to stay on screen at precisely the moment a clear-and-replace would
 * wipe them, which is the phase's second named risk.
 *
 * **Two limit messages, never merged.** `SESSION_LIMIT_MESSAGE` is this app's
 * own two-run counter, per device, resetting on the hour. `SHOWCASE_LIMIT_MESSAGE`
 * is the gallery-wide allowance the server refused the run with. They have
 * different owners and different remedies, and a visitor who cannot tell which
 * they hit cannot tell whether waiting will help.
 */
export function ReactLoopApp() {
  const presets = useReactPresets()
  const allowance = useRunAllowance()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [typed, setTyped] = useState('')

  // The advisory. Held here rather than in the form so that Start's enabled
  // state — computed in the form — has no access to it at all.
  const [suitability, setSuitability] = useState<QuestionSuitability | null>(null)
  const [checking, setChecking] = useState(false)
  const [checked, setChecked] = useState(false)
  const [refusal, setRefusal] = useState<string | null>(null)
  const sessionRef = useRef(`react-${Math.random().toString(36).slice(2, 12)}`)
  const lastChecked = useRef('')

  /**
   * Ask for the advisory. Fired on **blur**, not on every keystroke.
   *
   * The server owns the real controls — a hash cache, a per-session cap and a
   * length precheck — because a client-side limit protects nothing against a
   * client that does not implement it. This is the optimisation on top: not
   * asking again for text already asked about, and not asking at all until the
   * visitor has stopped typing.
   *
   * Every failure resolves to the neutral state. A moderation refusal is the
   * one exception, because that genuinely is an error the visitor must see —
   * and it is shown as a refusal, never as an advisory.
   */
  const requestSuitability = useCallback(() => {
    const question = typed.trim()
    // An over-length question is refused client-side, so asking about it would
    // spend one of the session's five checks on text that cannot be run.
    if (
      question === '' ||
      question.length > MAX_QUESTION_CHARS ||
      question === lastChecked.current
    ) {
      return
    }
    lastChecked.current = question
    setChecking(true)
    setRefusal(null)

    void checkSuitability(question, sessionRef.current)
      .then((response) => {
        setSuitability(response.verdict)
        setChecked(true)
      })
      .catch((cause: unknown) => {
        if (cause instanceof ReactRequestError && cause.code.startsWith('moderation')) {
          setRefusal(cause.message)
          setSuitability(null)
          setChecked(false)
          return
        }
        // Anything else is the neutral state: an advisory that could not be
        // produced must not read as the app being broken.
        setSuitability(null)
        setChecked(true)
      })
      .finally(() => setChecking(false))
  }, [typed])

  const onFinish = useCallback(
    (run: { runId: string; question: string; ending: 'answer' | 'exhausted' }) => {
      allowance.complete(run)
    },
    [allowance],
  )

  const run = useReactRun(onFinish)
  const { state } = run

  // The server's refusal, distinct from the local counter's.
  const showcaseRefused =
    state.phase === 'refused' && state.error?.code === 'usage_limit_reached'

  const limitMessage = showcaseRefused
    ? SHOWCASE_LIMIT_MESSAGE
    : allowance.exhausted
      ? SESSION_LIMIT_MESSAGE
      : null

  const budget = state.cycleBudget || presets.data?.cycleBudget || 0

  return (
    <div className="space-y-6">
      {/* Overview first, then the input, then the results — the same relative
          order every other example app on this gallery uses. */}
      <PatternOverview />

      <QuestionForm
        presets={presets.data?.presets ?? []}
        selectedId={selectedId}
        typed={typed}
        onSelect={(id) => {
          setSelectedId(id)
          // A preset outranks free text server-side, so the box is cleared
          // rather than left showing a question the run would not use.
          setTyped('')
          // A preset is pre-vetted: it skips the gate and the advisory alike.
          setSuitability(null)
          setChecked(false)
          setRefusal(null)
          lastChecked.current = ''
        }}
        onType={(value) => {
          setTyped(value)
          setSelectedId(null)
          // The advisory belongs to the text that produced it.
          setSuitability(null)
          setChecked(false)
          setRefusal(null)
        }}
        onQuestionBlur={requestSuitability}
        suitability={suitability}
        checking={checking}
        checked={checked}
        refusal={refusal}
        onStart={() =>
          run.start(
            selectedId !== null
              ? { presetQuestionId: selectedId }
              : { visitorQuestion: typed.trim() },
          )
        }
        onStop={run.stop}
        pending={run.pending}
        exhausted={allowance.exhausted}
        remaining={allowance.remaining}
        cap={allowance.allowance.cap}
        cycleBudget={budget}
        limitMessage={limitMessage}
      />

      {presets.isError && (
        <p className="text-sm text-red-600 dark:text-red-400">
          {presets.error instanceof Error
            ? presets.error.message
            : 'The curated questions could not be loaded.'}
        </p>
      )}

      {/* Left mounted through exhaustion: prior results must stay on screen. */}
      <TraceStream state={state} pending={run.pending} />

      {state.terminal?.kind === 'answer' && (
        <AnswerCard
          answer={state.terminal.answer}
          observationCycles={state.terminal.observationCycles}
          unverified={state.terminal.audit.unverified}
          searchesUsed={state.terminal.searchesUsed}
          cycleBudget={state.terminal.cycleBudget}
        />
      )}

      {state.terminal?.kind === 'exhausted' && (
        <ExhaustedCard
          unresolved={state.terminal.unresolved}
          partialFindings={state.terminal.partialFindings}
          searchesUsed={state.terminal.searchesUsed}
          cycleBudget={state.terminal.cycleBudget}
        />
      )}

      {/* Additive: absent annotations render nothing at all, never an error. */}
      <AnnotationPanel
        annotations={state.annotations}
        exhausted={state.terminal?.kind === 'exhausted'}
      />

      {state.phase === 'unreachable' && state.error !== null && (
        <p
          data-testid="react-unreachable"
          role="alert"
          className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:bg-red-950/40 dark:text-red-300"
        >
          {state.error.message}
        </p>
      )}

      {state.phase === 'refused' && state.error !== null && !showcaseRefused && (
        <p
          data-testid="react-refused"
          role="alert"
          className="rounded-lg border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
        >
          {state.error.message}
        </p>
      )}

      <PriorRuns runs={allowance.runs} currentRunId={state.runId} />
    </div>
  )
}

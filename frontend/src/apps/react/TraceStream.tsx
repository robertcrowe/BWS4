// Built with Spec4 AI - https://spec4.ai
import { Markdown } from '../../components/Markdown'
import { counterLabel } from './runState'
import type { RunState, TraceCycle } from './runState'

/**
 * `react_trace_stream`: the loop, filling cycle by cycle as envelopes arrive.
 *
 * Layout follows `.spec4/v7/design/mock.html`'s `#screen-react`: a cycle card
 * per cycle carrying a numbered badge and a kind chip, then Thought / Action /
 * Observation rows, with the exact query in a monospace box and each snippet
 * attributed by title and source.
 *
 * **The mock's typing animation is deliberately not built.** A thought arrives
 * complete in a single SSE envelope, so revealing it character by character
 * would be inventing a stream the server never sent — the fifth time this
 * project has declined that, after the tool-use step indicator, the
 * chained-calls hand-off, the orchestrated typing effect and the collaboration
 * stage rail. What is real, and what this renders, is one cycle appearing at a
 * time with the counter advancing between them.
 *
 * **Snippets are escaped text, never markdown and never HTML.** They are
 * untrusted third-party web results on an unauthenticated public page, so they
 * go into the DOM as text nodes and their links are shown as text rather than
 * anchors — nothing here is auto-followable. Only the model's own prose goes
 * through the shared `Markdown` wrapper, which itself never uses
 * `dangerouslySetInnerHTML`.
 */

/** Props for {@link TraceStream}. */
export interface TraceStreamProps {
  state: RunState
  /** True while the stream is open, so the counter can show it is live. */
  pending: boolean
}

/**
 * Render the live trace and its cycle counter.
 *
 * @param props - The run state and whether the stream is still open.
 * @returns The trace region, or nothing before a run starts.
 */
export function TraceStream({ state, pending }: TraceStreamProps) {
  if (state.phase === 'idle') {
    return null
  }

  return (
    <section
      data-testid="react-trace"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          Live trace — reason → act → observe
        </h3>
        <span
          data-testid="react-cycle-counter"
          aria-label={`Search budget: ${counterLabel(state)}`}
          className="inline-flex items-center gap-2 rounded-full border border-gray-200 bg-gray-50 px-3 py-1 font-mono text-xs text-gray-700 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-300"
        >
          {pending && (
            <span
              aria-hidden="true"
              className="h-2 w-2 animate-pulse rounded-full bg-violet-500"
            />
          )}
          {counterLabel(state)}
        </span>
      </div>

      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
        Each cycle&apos;s next step is decided only after the observation above it.
        Nothing is planned ahead and you approve nothing mid-run.
      </p>

      {state.phase === 'connecting' && (
        <p
          data-testid="react-connecting"
          className="mt-4 text-sm text-gray-500 dark:text-gray-400"
        >
          Starting the run…
        </p>
      )}

      {/*
        **One live region for the whole run, and it is not this list.**

        Marking the trace itself `aria-live` announces every mutation inside it
        — a cycle changes three times as its thought, action and observation
        arrive, and each observation adds five snippets — so a screen reader
        would read the entire trace aloud several times over. That is the
        over-announcement the accessibility pass exists to catch.

        Instead the list is a `log`: readable on demand, navigable by heading
        and list semantics, and silent. The single status line below announces
        one short sentence per cycle boundary.
      */}
      <p className="sr-only" role="status" data-testid="react-trace-announcer">
        {announcement(state)}
      </p>

      <ol
        role="log"
        aria-label="Reason, act and observe cycles"
        className="mt-4 space-y-3"
      >
        {state.cycles.map((cycle) => (
          <CycleCard key={cycle.cycle} cycle={cycle} />
        ))}
      </ol>
    </section>
  )
}

/**
 * One short sentence describing where the run has got to.
 *
 * Deliberately terse and *replaced* rather than appended: a screen reader reads
 * this element's new contents on each change, so it must be a status, not a
 * transcript.
 *
 * @param state - The run state.
 * @returns What to announce, or an empty string when there is nothing new.
 */
function announcement(state: RunState): string {
  if (state.terminal?.kind === 'answer') {
    return 'Run complete. A final answer is ready.'
  }
  if (state.terminal?.kind === 'exhausted') {
    return 'Run ended without an answer. The budget-exhausted card explains what remained unresolved.'
  }
  const latest = state.cycles.at(-1)
  if (!latest) {
    return state.phase === 'connecting' ? 'Starting the run.' : ''
  }
  if (latest.observationStatus === 'unavailable') {
    return `Cycle ${latest.cycle}: the search could not be run.`
  }
  if (latest.observationStatus === 'empty') {
    return `Cycle ${latest.cycle}: the search returned no results.`
  }
  if (latest.observationStatus === 'ok') {
    return `Cycle ${latest.cycle}: observation returned with ${latest.results.length} results.`
  }
  if (latest.actionKind === 'answer') {
    return `Cycle ${latest.cycle}: the model decided it can answer.`
  }
  if (latest.actionKind === 'search') {
    return `Cycle ${latest.cycle}: searching.`
  }
  return `Cycle ${latest.cycle}: thinking.`
}

const PHASE_BORDER: Record<TraceCycle['phase'], string> = {
  thinking: 'border-l-gray-300 dark:border-l-gray-600',
  searching: 'border-l-violet-500',
  observed: 'border-l-blue-500',
  answered: 'border-l-emerald-500',
}

function CycleCard({ cycle }: { cycle: TraceCycle }) {
  return (
    <li
      id={`react-cycle-${cycle.cycle}`}
      data-testid={`react-cycle-${cycle.cycle}`}
      className={`rounded-xl border border-l-[3px] border-gray-200 bg-gray-50 p-4 dark:border-gray-800 dark:bg-gray-950 ${PHASE_BORDER[cycle.phase]}`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-gradient-to-r from-violet-600 to-blue-600 px-2.5 py-0.5 font-mono text-[11px] text-white">
          cycle {cycle.cycle}
        </span>
        <KindChip cycle={cycle} />
      </div>

      <Row name="Thought">
        <span className="text-gray-700 dark:text-gray-300">{cycle.thought}</span>
      </Row>

      {cycle.actionKind === 'search' && cycle.query !== null && (
        <Row name="Action">
          <span className="text-gray-700 dark:text-gray-300">
            Issued a web search — exact query:{' '}
            <code
              data-testid={`react-query-${cycle.cycle}`}
              className="inline-block rounded-md border border-gray-300 bg-white px-2 py-0.5 font-mono text-xs break-all text-gray-900 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
            >
              {cycle.query}
            </code>
          </span>
        </Row>
      )}

      {cycle.actionKind === 'answer' && (
        <Row name="Action">
          <span className="text-gray-700 dark:text-gray-300">
            Declared it can now answer from the observations already in hand — no
            further search issued.
          </span>
        </Row>
      )}

      {cycle.actionKind === 'search' && <Observation cycle={cycle} />}
    </li>
  )
}

function KindChip({ cycle }: { cycle: TraceCycle }) {
  const label =
    cycle.actionKind === null
      ? 'thinking…'
      : cycle.actionKind === 'answer'
        ? 'action: answer'
        : 'action: search'
  const tone =
    cycle.actionKind === 'answer'
      ? 'border-emerald-400 text-emerald-700 dark:text-emerald-300'
      : cycle.actionKind === 'search'
        ? 'border-blue-400 text-blue-700 dark:text-blue-300'
        : 'border-gray-300 text-gray-500 dark:border-gray-700 dark:text-gray-400'
  return (
    <span
      className={`rounded-full border bg-white px-2 py-0.5 font-mono text-[10px] uppercase tracking-wide dark:bg-gray-900 ${tone}`}
    >
      {label}
    </span>
  )
}

function Observation({ cycle }: { cycle: TraceCycle }) {
  if (cycle.observationStatus === null) {
    return (
      <Row name="Observation">
        <span className="text-gray-500 dark:text-gray-400">
          waiting on the search tool…
        </span>
      </Row>
    )
  }

  // A failed search and an empty one are different facts and get different
  // visible states: one is the demonstration failing, the other is the web's
  // answer to the question. Neither may render as a blank cycle.
  if (cycle.observationStatus === 'unavailable') {
    return (
      <Row name="Observation">
        <span
          data-testid={`react-observation-unavailable-${cycle.cycle}`}
          className="text-amber-700 dark:text-amber-400"
        >
          ⚠ Search unavailable — {cycle.observationDetail ?? 'the search could not be run.'}{' '}
          This is a tool failure, not evidence about the world.
        </span>
      </Row>
    )
  }

  if (cycle.observationStatus === 'empty') {
    return (
      <Row name="Observation">
        <span
          data-testid={`react-observation-empty-${cycle.cycle}`}
          className="text-amber-700 dark:text-amber-400"
        >
          No results — the search returned nothing. The next thought has to work
          around the miss rather than fill it in.
        </span>
      </Row>
    )
  }

  return (
    <Row name={`Observation ${cycle.observationIndex ?? ''}`.trim()}>
      <ul className="space-y-2">
        {cycle.results.map((result) => (
          <li
            key={result.idx}
            className="rounded-lg border border-gray-200 bg-white p-2.5 dark:border-gray-800 dark:bg-gray-900"
          >
            <strong className="block text-xs text-gray-900 dark:text-gray-100">
              [{result.idx}] {result.title}
            </strong>
            {/* Escaped text. These are untrusted web results. */}
            <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
              {result.snippet}
              {result.truncated && (
                <span className="text-gray-400"> […truncated]</span>
              )}
            </p>
            <p className="mt-1 font-mono text-[10px] break-all text-gray-500 dark:text-gray-500">
              {/* Rendered as text, never an anchor: nothing here is auto-followable. */}
              {result.url} · {result.published_date ?? 'undated'}
            </p>
          </li>
        ))}
      </ul>
    </Row>
  )
}

function Row({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    // Stacked on a narrow screen, two columns from `sm` up. A fixed 6rem label
    // column beside prose is fine at desktop width and squeezes the content to
    // a few words per line on a phone, which is where the per-cycle grouping
    // stops being legible -- the one thing the responsive pass has to protect.
    <div className="mt-2 flex flex-col gap-1 border-t border-dashed border-gray-200 pt-2 first-of-type:border-t-0 sm:flex-row sm:gap-3 dark:border-gray-800">
      <span className="shrink-0 pt-0.5 font-mono text-[10px] uppercase tracking-wide text-gray-500 sm:w-24 dark:text-gray-500">
        {name}
      </span>
      <div className="min-w-0 flex-1 text-sm break-words">{children}</div>
    </div>
  )
}

/**
 * The final-answer card, with the observations it drew on and the audit.
 *
 * @param props - The terminal state.
 * @returns The answer card.
 */
export function AnswerCard({
  answer,
  observationCycles,
  unverified,
  searchesUsed,
  cycleBudget,
}: {
  answer: string
  observationCycles: number[]
  unverified: number[]
  searchesUsed: number
  cycleBudget: number
}) {
  return (
    <section
      data-testid="react-answer-card"
      aria-label="Final answer"
      className="rounded-2xl border-2 border-emerald-500 bg-emerald-50/60 p-5 dark:bg-emerald-950/30"
    >
      <div className="flex flex-wrap items-center gap-2">
        {/* Distinguishable by text and icon, not colour alone. */}
        <span className="rounded-full border border-emerald-500 px-3 py-1 font-mono text-xs text-emerald-800 dark:text-emerald-300">
          ✓ Ending: final answer
        </span>
        <span className="font-mono text-xs text-gray-600 dark:text-gray-400">
          loop closed after {searchesUsed} of {cycleBudget} searches
        </span>
      </div>

      <div className="mt-3 text-sm text-gray-900 dark:text-gray-100">
        <Markdown variant="lead">{answer}</Markdown>
      </div>

      <p className="mt-3 text-xs text-gray-600 dark:text-gray-400">
        Drew on{' '}
        {observationCycles.length > 0
          ? `observation${observationCycles.length > 1 ? 's' : ''} ${observationCycles.join(', ')}`
          : 'no observation — this answer came from the model’s own knowledge'}
        . Every query issued and every snippet returned is shown verbatim above.
      </p>

      {unverified.length > 0 && (
        <p
          data-testid="react-audit-unverified"
          className="mt-2 rounded-lg border border-amber-400 bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
        >
          ⚠ The answer cited observation{unverified.length > 1 ? 's' : ''}{' '}
          {unverified.join(', ')}, which this run never produced. Shown rather
          than quietly accepted.
        </p>
      )}
    </section>
  )
}

/**
 * The budget-exhausted card. Never styled or worded as an answer.
 *
 * @param props - The terminal state.
 * @returns The exhausted card.
 */
export function ExhaustedCard({
  unresolved,
  partialFindings,
  searchesUsed,
  cycleBudget,
}: {
  unresolved: string[]
  partialFindings: number[]
  searchesUsed: number
  cycleBudget: number
}) {
  return (
    <section
      data-testid="react-exhausted-card"
      aria-label="Run ended without an answer"
      className="rounded-2xl border-2 border-amber-500 bg-amber-50/60 p-5 dark:bg-amber-950/30"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-amber-500 px-3 py-1 font-mono text-xs text-amber-800 dark:text-amber-300">
          ⚠ Ending: budget exhausted
        </span>
        <span className="font-mono text-xs text-gray-600 dark:text-gray-400">
          no answer produced — {searchesUsed} of {cycleBudget} searches used
        </span>
      </div>

      <p className="mt-3 rounded-lg border border-amber-400 bg-amber-100/70 p-2.5 text-xs text-amber-900 dark:bg-amber-900/30 dark:text-amber-200">
        This run stopped before it could answer. It is presented as an
        unfinished run, not as an answer.
      </p>

      <div className="mt-3 text-sm text-gray-800 dark:text-gray-200">
        <strong className="text-xs uppercase tracking-wide text-gray-600 dark:text-gray-400">
          What remained unresolved
        </strong>
        <ul className="mt-1 list-disc space-y-1 pl-5">
          {unresolved.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>

      {partialFindings.length > 0 && (
        <p className="mt-3 text-xs text-gray-600 dark:text-gray-400">
          Observations {partialFindings.join(', ')} did return results — the
          partial trace above is what the run established before it stopped.
        </p>
      )}
    </section>
  )
}

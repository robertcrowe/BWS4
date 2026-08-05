// Built with Spec4 AI - https://spec4.ai
/**
 * The ReAct screen: progressive rendering, the counter, the two endings, and
 * the exhausted state.
 *
 * **The load-bearing test in this file is `renders each cycle as its envelope
 * arrives`.** The phase's first named risk is a consumer that accumulates
 * envelopes and sets state once at stream close: it would satisfy every
 * assertion about the finished screen while destroying what the app is for,
 * because the loop's visible progression *is* the lesson. So envelopes are
 * delivered one at a time and the DOM is asserted to grow between them — which
 * a buffered implementation cannot do.
 *
 * The second risk is the exhausted state being a clear-and-replace that wipes
 * previous traces at exactly the moment the spec requires them kept, so that is
 * asserted directly rather than inferred from the controls being disabled.
 *
 * Driven by a mocked envelope sequence, never a live backend.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchReactPresets, startReactRun } from '../src/api/react'
import type { ReactPresetsResponse, ReactRunEvent } from '../src/api/react'
import { ReactLoopApp } from '../src/apps/react/ReactLoopApp'
import {
  RUN_CAP,
  SESSION_LIMIT_MESSAGE,
  SHOWCASE_LIMIT_MESSAGE,
  STORAGE_KEY,
  utcWindow,
} from '../src/apps/react/runAllowance'

vi.mock('../src/api/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/api/react')>()
  return {
    ...actual,
    fetchReactPresets: vi.fn(),
    startReactRun: vi.fn(),
    fetchReactRun: vi.fn(),
  }
})

const mockedPresets = vi.mocked(fetchReactPresets)
const mockedRun = vi.mocked(startReactRun)

const PRESETS: ReactPresetsResponse = {
  setVersion: 'v1',
  cycleBudget: 8,
  presets: [
    {
      id: 'p1',
      label: 'Highest mountain in the newest UN member',
      question: 'How tall is the highest mountain in the newest UN member?',
      hopCount: 2,
      guaranteedFullyObserved: true,
    },
  ],
}

/** Hands the component a sink it can push envelopes into, one at a time. */
function manualStream() {
  let emit: (event: ReactRunEvent) => void = () => {}
  let resolve: () => void = () => {}

  mockedRun.mockImplementation(async (options) => {
    emit = options.onEvent
    await new Promise<void>((done) => {
      resolve = done
    })
  })

  return {
    /** Deliver one envelope and let React flush it. */
    async send(event: ReactRunEvent) {
      await act(async () => {
        emit(event)
      })
    },
    async close() {
      await act(async () => {
        resolve()
      })
    },
  }
}

function started(overrides: Partial<Extract<ReactRunEvent, { kind: 'run_started' }>> = {}) {
  return {
    kind: 'run_started' as const,
    run_id: 'run-1',
    question: PRESETS.presets[0].question,
    question_source: 'preset' as const,
    preset_id: 'p1',
    cycle_budget: 8,
    runs_remaining: 2,
    stub: false,
    ...overrides,
  }
}

function counter(searches: number) {
  return {
    kind: 'cycle_counter' as const,
    searches_used: searches,
    cycle_budget: 8,
    stub: false,
  }
}

function thought(cycle: number, text: string) {
  return { kind: 'cycle_thought' as const, cycle, thought: text, stub: false }
}

function searchAction(cycle: number, query: string) {
  return {
    kind: 'cycle_action' as const,
    cycle,
    action_kind: 'search' as const,
    query,
    rationale: '',
    stub: false,
  }
}

function observation(
  index: number,
  overrides: Partial<Extract<ReactRunEvent, { kind: 'cycle_observation' }>> = {},
) {
  return {
    kind: 'cycle_observation' as const,
    index,
    query: 'a query',
    results: [
      {
        idx: 1,
        title: `Result for observation ${index}`,
        snippet: `Snippet ${index}.`,
        url: 'https://example.org/a',
        published_date: '2026-01-01',
        truncated: false,
      },
    ],
    is_empty: false,
    status: 'ok' as const,
    detail: null,
    truncated: false,
    stub: false,
    ...overrides,
  }
}

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ReactLoopApp />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function selectPresetAndStart() {
  const user = userEvent.setup()
  // Wait for the chip, not the container: the container renders immediately and
  // empty while the presets query is still in flight.
  const chip = await screen.findByRole('button', { name: /newest UN member/i })
  await user.click(chip)
  await user.click(screen.getByRole('button', { name: /start run/i }))
  return user
}

beforeEach(() => {
  window.localStorage.clear()
  mockedPresets.mockReset()
  mockedPresets.mockResolvedValue(PRESETS)
  mockedRun.mockReset()
})

describe('the trace fills as envelopes arrive', () => {
  it('renders each cycle as its envelope arrives, not at stream close', async () => {
    // The file's central assertion. A consumer that buffered envelopes and set
    // state once at the end would pass every check on the finished screen and
    // fail this one, because the DOM would not grow in between.
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    expect(screen.queryByTestId('react-cycle-1')).toBeNull()

    await stream.send(counter(0))
    await stream.send(thought(1, 'I need the newest UN member.'))
    expect(screen.getByTestId('react-cycle-1')).toBeInTheDocument()
    expect(screen.queryByTestId('react-cycle-2')).toBeNull()

    await stream.send(searchAction(1, 'most recent country to join UN'))
    expect(screen.getByTestId('react-query-1')).toHaveTextContent(
      'most recent country to join UN',
    )

    await stream.send(observation(1))
    expect(screen.getByTestId('react-cycle-1')).toHaveTextContent(
      'Result for observation 1',
    )

    // Only now does the second cycle exist — which is the point.
    await stream.send(counter(1))
    await stream.send(thought(2, 'South Sudan. Now its highest mountain.'))
    expect(screen.getByTestId('react-cycle-2')).toBeInTheDocument()
  })

  it('shows a thought that builds on the observation above it', async () => {
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    await stream.send(thought(1, 'I need the newest UN member.'))
    await stream.send(searchAction(1, 'newest UN member'))
    await stream.send(observation(1))
    await stream.send(thought(2, 'South Sudan. Now its highest mountain.'))

    const cycles = screen.getAllByTestId(/^react-cycle-\d+$/)
    expect(cycles).toHaveLength(2)
    expect(cycles[1]).toHaveTextContent('South Sudan')
  })

  it('renders the cycles in arrival order, oldest first', async () => {
    // Document order, not merely presence. A trace whose newest cycle appeared
    // at the top would still contain everything and would still grow between
    // envelopes -- and would have destroyed the one thing the exhibit shows,
    // which is a chain being built forwards.
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    for (const cycle of [1, 2, 3]) {
      await stream.send(counter(cycle - 1))
      await stream.send(thought(cycle, `Thought number ${cycle}.`))
      await stream.send(searchAction(cycle, `query number ${cycle}`))
      await stream.send(observation(cycle))
    }

    const rendered = screen
      .getAllByTestId(/^react-cycle-\d+$/)
      .map((node) => node.getAttribute('data-testid'))
    expect(rendered).toEqual(['react-cycle-1', 'react-cycle-2', 'react-cycle-3'])
  })

  it('advances the cycle counter as counter envelopes arrive', async () => {
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    await stream.send(counter(0))
    expect(screen.getByTestId('react-cycle-counter')).toHaveTextContent('search 0 of 8')

    await stream.send(counter(1))
    expect(screen.getByTestId('react-cycle-counter')).toHaveTextContent('search 1 of 8')

    await stream.send(counter(2))
    expect(screen.getByTestId('react-cycle-counter')).toHaveTextContent('search 2 of 8')
  })

  it('reads the budget from the server rather than hardcoding eight', async () => {
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started({ cycle_budget: 5 }))
    await stream.send({ ...counter(2), cycle_budget: 5 })

    expect(screen.getByTestId('react-cycle-counter')).toHaveTextContent('search 2 of 5')
  })

  it('shows the exact query issued for every search', async () => {
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    await stream.send(thought(1, 't'))
    await stream.send(searchAction(1, 'the precise query text'))

    expect(screen.getByTestId('react-query-1')).toHaveTextContent('the precise query text')
  })

  it('renders snippets as inert text with their source and date', async () => {
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    await stream.send(thought(1, 't'))
    await stream.send(searchAction(1, 'q'))
    await stream.send(
      observation(1, {
        results: [
          {
            idx: 1,
            title: '<img src=x onerror=alert(1)>',
            snippet: 'A snippet with <b>markup</b> in it.',
            url: 'https://example.org/page',
            published_date: null,
            truncated: false,
          },
        ],
      }),
    )

    // Untrusted third-party web results on a public page: text nodes, no tags,
    // and no anchor a click could follow.
    expect(screen.getByText(/onerror=alert\(1\)/)).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
    expect(screen.getByText(/https:\/\/example\.org\/page/)).toBeInTheDocument()
    expect(screen.getByText(/undated/)).toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: /example\.org/ }),
    ).toBeNull()
  })

  it('renders an empty observation as a visible no-results state', async () => {
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    await stream.send(thought(1, 't'))
    await stream.send(searchAction(1, 'q'))
    await stream.send(observation(1, { results: [], is_empty: true, status: 'empty' }))

    expect(screen.getByTestId('react-observation-empty-1')).toHaveTextContent(/no results/i)
  })

  it('renders a failed search as a visible search-unavailable state', async () => {
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    await stream.send(thought(1, 't'))
    await stream.send(searchAction(1, 'q'))
    await stream.send(
      observation(1, {
        results: [],
        is_empty: true,
        status: 'unavailable',
        detail: 'The search service could not be reached for this cycle.',
      }),
    )

    const shown = screen.getByTestId('react-observation-unavailable-1')
    expect(shown).toHaveTextContent(/search unavailable/i)
    // Not "nothing was found": a broken tool is not evidence about the world.
    expect(shown).toHaveTextContent(/not evidence about the world/i)
  })
})

describe('the two terminal cards', () => {
  it('shows a final-answer card naming the observations it drew on', async () => {
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    await stream.send({
      kind: 'final_answer',
      run_id: 'run-1',
      answer: 'Mount Kinyeti, 3,187 metres.',
      observation_cycles: [1, 2],
      audit: { all_cited_present: true, cited: [1, 2], unverified: [] },
      searches_used: 2,
      cycle_budget: 8,
      stub: false,
    })

    const card = screen.getByTestId('react-answer-card')
    expect(card).toHaveTextContent('Mount Kinyeti')
    expect(card).toHaveTextContent(/observations 1, 2/)
    expect(screen.queryByTestId('react-exhausted-card')).toBeNull()
  })

  it('surfaces an unverified citation rather than accepting it silently', async () => {
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    await stream.send({
      kind: 'final_answer',
      run_id: 'run-1',
      answer: 'An answer.',
      observation_cycles: [1, 4],
      audit: { all_cited_present: false, cited: [1, 4], unverified: [4] },
      searches_used: 1,
      cycle_budget: 8,
      stub: false,
    })

    expect(screen.getByTestId('react-audit-unverified')).toHaveTextContent(
      /cited observation 4, which this run never produced/i,
    )
  })

  it('shows a budget-exhausted card that is never worded as an answer', async () => {
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    await stream.send({
      kind: 'budget_exhausted',
      run_id: 'run-1',
      reason: 'search_ceiling',
      unresolved: ['The run reached its ceiling of 8 searches.'],
      partial_findings: [1, 2],
      searches_used: 8,
      cycle_budget: 8,
      stub: false,
    })

    const card = screen.getByTestId('react-exhausted-card')
    expect(card).toHaveTextContent(/budget exhausted/i)
    expect(card).toHaveTextContent(/not as an answer/i)
    expect(card).toHaveTextContent(/what remained unresolved/i)
    expect(screen.queryByTestId('react-answer-card')).toBeNull()
  })

  it('distinguishes the two cards by more than colour', async () => {
    // Accessibility requirement: an accessible name and a text marker, so the
    // two endings are not told apart by a border colour alone.
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    await stream.send({
      kind: 'budget_exhausted',
      run_id: 'run-1',
      reason: 'wall_clock',
      unresolved: ['Out of time.'],
      partial_findings: [],
      searches_used: 3,
      cycle_budget: 8,
      stub: false,
    })

    expect(
      screen.getByRole('region', { name: /run ended without an answer/i }),
    ).toBeInTheDocument()
  })

  it('emits exactly one terminal card per run', async () => {
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    await stream.send({
      kind: 'final_answer',
      run_id: 'run-1',
      answer: 'An answer.',
      observation_cycles: [1],
      audit: { all_cited_present: true, cited: [1], unverified: [] },
      searches_used: 1,
      cycle_budget: 8,
      stub: false,
    })

    expect(screen.getAllByTestId(/react-(answer|exhausted)-card/)).toHaveLength(1)
  })
})

describe('no plan and no mid-run approval', () => {
  it('starts the run immediately, showing no plan and asking nothing', async () => {
    // The precise contrast with the Planning Agent example, asserted
    // structurally: pressing start opens the stream, and no confirmation
    // control exists anywhere on the screen.
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    expect(mockedRun).toHaveBeenCalledTimes(1)
    await stream.send(started())

    expect(screen.queryByRole('button', { name: /approve|confirm|go ahead|execute/i })).toBeNull()
    expect(screen.queryByText(/review the plan/i)).toBeNull()
  })

  it('sends the preset id rather than the question text', async () => {
    manualStream()
    renderApp()
    await selectPresetAndStart()

    expect(mockedRun).toHaveBeenCalledWith(
      expect.objectContaining({ presetQuestionId: 'p1' }),
    )
  })
})

describe('the two-run session allowance', () => {
  it('shows the runs remaining at all times', async () => {
    manualStream()
    renderApp()

    expect(await screen.findByTestId('react-runs-remaining')).toHaveTextContent(
      `${RUN_CAP} of ${RUN_CAP} runs remaining`,
    )
  })

  it('spends a run when one finishes, not when it starts', async () => {
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    expect(screen.getByTestId('react-runs-remaining')).toHaveTextContent('2 of 2')

    await stream.send({
      kind: 'final_answer',
      run_id: 'run-1',
      answer: 'An answer.',
      observation_cycles: [1],
      audit: { all_cited_present: true, cited: [1], unverified: [] },
      searches_used: 1,
      cycle_budget: 8,
      stub: false,
    })

    await waitFor(() => {
      expect(screen.getByTestId('react-runs-remaining')).toHaveTextContent('1 of 2')
    })
  })

  it('disables the controls but leaves every previous trace on screen', async () => {
    // The phase's second named risk: an exhausted state implemented as a
    // clear-and-replace wipes the results at exactly the moment the spec
    // requires them kept.
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        used: RUN_CAP - 1,
        cap: RUN_CAP,
        window: utcWindow(),
        runs: [{ runId: 'earlier', question: 'An earlier question', ending: 'answer' }],
      }),
    )

    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send(started())
    await stream.send(thought(1, 'A thought that must survive.'))
    await stream.send(searchAction(1, 'a query that must survive'))
    await stream.send(observation(1))
    await stream.send({
      kind: 'final_answer',
      run_id: 'run-1',
      answer: 'An answer that must survive.',
      observation_cycles: [1],
      audit: { all_cited_present: true, cited: [1], unverified: [] },
      searches_used: 1,
      cycle_budget: 8,
      stub: false,
    })

    await stream.close()

    await waitFor(() => {
      expect(screen.getByTestId('react-limit-message')).toBeInTheDocument()
    })

    expect(screen.getByRole('button', { name: /start run/i })).toBeDisabled()
    expect(screen.getByLabelText(/question \(or write your own\)/i)).toBeDisabled()

    // The whole point: the trace is still there.
    expect(screen.getByTestId('react-cycle-1')).toBeInTheDocument()
    expect(screen.getByText('A thought that must survive.')).toBeInTheDocument()
    expect(screen.getByTestId('react-query-1')).toHaveTextContent(
      'a query that must survive',
    )
    expect(screen.getByTestId('react-answer-card')).toHaveTextContent(
      'An answer that must survive.',
    )
  })

  it('names this app’s limit, distinctly from the shared framework cap', async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ used: RUN_CAP, cap: RUN_CAP, window: utcWindow(), runs: [] }),
    )
    manualStream()
    renderApp()

    const message = await screen.findByTestId('react-limit-message')
    expect(message).toHaveTextContent(SESSION_LIMIT_MESSAGE)
    expect(message).toHaveTextContent(/this demo's own limit/i)
    expect(message).toHaveTextContent(/not the showcase-wide allowance/i)
  })

  it('renders the server’s own cap refusal, which is a different limit', async () => {
    const stream = manualStream()
    renderApp()
    await selectPresetAndStart()

    await stream.send({
      kind: 'error',
      code: 'usage_limit_reached',
      message: 'The showcase allowance is used up.',
      stub: false,
    })

    const message = await screen.findByTestId('react-limit-message')
    expect(message).toHaveTextContent(SHOWCASE_LIMIT_MESSAGE)
    expect(message).toHaveTextContent(/showcase-wide/i)
    expect(message).toHaveTextContent(/not this demo's own two-run limit/i)
  })

  it('keeps the two limit messages distinct', () => {
    expect(SESSION_LIMIT_MESSAGE).not.toEqual(SHOWCASE_LIMIT_MESSAGE)
  })
})

describe('the stop control', () => {
  it('appears while a run is in flight and aborts it', async () => {
    const stream = manualStream()
    renderApp()
    const user = await selectPresetAndStart()

    await stream.send(started())
    const stop = screen.getByRole('button', { name: /stop run/i })
    await user.click(stop)

    const signal = mockedRun.mock.calls[0][0].signal
    expect(signal?.aborted).toBe(true)
  })

  it('aborts the stream on unmount', async () => {
    const stream = manualStream()
    const { unmount } = renderApp()
    await selectPresetAndStart()
    await stream.send(started())

    unmount()

    expect(mockedRun.mock.calls[0][0].signal?.aborted).toBe(true)
  })
})

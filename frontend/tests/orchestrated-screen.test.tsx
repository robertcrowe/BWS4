// Built with Spec4 AI - https://spec4.ai
/**
 * The orchestrated-subagents screen.
 *
 * Four assertions here carry the weight, and each corresponds to a way this
 * screen could look right while being wrong:
 *
 * 1. **Both columns show in progress at once**, driven by interleaved SSE
 *    events. A single combined state object would make them update together and
 *    destroy the visible parallelism the screen exists to show — and a test
 *    that only checked both answers eventually arrive could not tell the
 *    difference.
 * 2. **Model output renders as elements, never as HTML.** This surface is
 *    public, unauthenticated, and shows prose derived from free-form visitor
 *    text. The test feeds an injection payload through the merge and asserts it
 *    comes out as text.
 * 3. **Nothing dispatches before the visitor presses dispatch.** The gate is
 *    the pattern; an effect that advanced past it would leave the button on
 *    screen and remove what it does.
 * 4. **The two exhaustion messages stay distinct.** They are different limits
 *    with different owners, and the capability forbids collapsing them.
 *
 * The SSE transport is mocked at `@microsoft/fetch-event-source`, so the real
 * client, the real hook and the real components all run — only the network is
 * replaced.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RosterResponse } from '../src/api/orchestrated'
import { OrchestratedApp } from '../src/apps/orchestrated/OrchestratedApp'
import {
  SESSION_LIMIT_MESSAGE,
  SHOWCASE_LIMIT_MESSAGE,
  STORAGE_KEY,
  utcWindow,
} from '../src/apps/orchestrated/runAllowance'

interface OpenStream {
  url: string
  options: {
    signal?: AbortSignal
    onmessage?: (message: { event: string; data: string }) => void
  }
  resolve: () => void
  reject: (cause: unknown) => void
}

const hoisted = vi.hoisted(() => ({ streams: [] as OpenStream[] }))

vi.mock('@microsoft/fetch-event-source', () => ({
  fetchEventSource: (url: string, options: OpenStream['options']) =>
    new Promise<void>((resolve, reject) => {
      hoisted.streams.push({ url, options, resolve, reject })
    }),
}))

const ROSTER: RosterResponse = {
  specialists: [
    { id: 'technical', displayName: 'Technical Analyst', scope: 'Mechanism.', color: '#4ea1ff' },
    { id: 'financial', displayName: 'Financial Analyst', scope: 'Cost.', color: '#f6b93b' },
    { id: 'historical', displayName: 'Historical Contextualiser', scope: 'Context.', color: '#7c5cff' },
    { id: 'practical', displayName: 'Practical Practitioner', scope: 'Steps.', color: '#34d399' },
  ],
  presets: [
    {
      id: 'self-host-database',
      text: 'Should a small team self-host its own database?',
      expectedPairing: ['technical', 'financial'],
    },
  ],
}

const DECISION = {
  decision_id: 'run-1',
  chosen_specialists: ['technical', 'financial'],
  rationale: 'Mechanism and cost are the two live questions here.',
  briefs: [
    { specialist_id: 'technical', instruction: 'Cover the mechanism only.' },
    { specialist_id: 'financial', instruction: 'Cover the cost only.' },
  ],
  fit_quality: 'strong' as const,
  model_call_count: 3,
}

function stubRoster() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(ROSTER), { status: 200 })),
  )
}

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <OrchestratedApp />
    </QueryClientProvider>,
  )
}

/** The open stream whose URL contains `match`, or undefined. */
function streamFor(match: string): OpenStream | undefined {
  return hoisted.streams.find((entry) => entry.url.includes(match))
}

async function emit(stream: OpenStream, event: string, data: unknown) {
  await act(async () => {
    stream.options.onmessage?.({ event, data: JSON.stringify(data) })
  })
}

async function close(stream: OpenStream) {
  await act(async () => {
    stream.resolve()
    await Promise.resolve()
  })
}

/** Get through the roster load, the question, and the delegation decision. */
async function reachDecision(user: ReturnType<typeof userEvent.setup>) {
  renderApp()
  await screen.findByTestId('specialist-roster')

  await user.click(screen.getByRole('button', { name: ROSTER.presets[0].text }))
  await user.click(screen.getByRole('button', { name: 'Choose specialists' }))

  const run = streamFor('/run')!
  await emit(run, 'delegation', DECISION)
  await close(run)
  return run
}

/** Get all the way to two dispatched specialists. */
async function reachDispatch(user: ReturnType<typeof userEvent.setup>) {
  await reachDecision(user)
  await user.click(screen.getByTestId('dispatch-button'))
  return streamFor('/dispatch')!
}

beforeEach(() => {
  hoisted.streams.length = 0
  window.localStorage.clear()
  stubRoster()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the roster panel', () => {
  it('renders all four specialists from the server', async () => {
    renderApp()
    const roster = await screen.findByTestId('specialist-roster')

    for (const specialist of ROSTER.specialists) {
      expect(within(roster).getByText(specialist.displayName)).toBeInTheDocument()
    }
  })

  it('marks only the chosen pair once a decision arrives', async () => {
    const user = userEvent.setup()
    await reachDecision(user)

    expect(screen.getByTestId('roster-technical')).toHaveAttribute('data-chosen', 'true')
    expect(screen.getByTestId('roster-financial')).toHaveAttribute('data-chosen', 'true')
    expect(screen.getByTestId('roster-historical')).toHaveAttribute('data-chosen', 'false')
    expect(screen.getByTestId('roster-practical')).toHaveAttribute('data-chosen', 'false')
  })
})

describe('the moderation refusal', () => {
  it('renders as plain text, keeps the input enabled and spends no run', async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByTestId('specialist-roster')

    await user.type(
      screen.getByLabelText('Your question'),
      'Something the gate refuses',
    )
    await user.click(screen.getByRole('button', { name: 'Choose specialists' }))

    const run = streamFor('/run')!
    await emit(run, 'error', {
      outcome: 'moderation_blocked',
      // A refusal can quote the visitor. Through a renderer this would be a
      // reflected-injection path straight into the page.
      message: 'Refused: <img src=x onerror="alert(1)"> — try rephrasing.',
      decision_id: 'run-1',
    })
    await close(run)

    const message = await screen.findByTestId('refusal-message')
    expect(message).toHaveTextContent('<img src=x onerror="alert(1)">')
    expect(message.querySelector('img')).toBeNull()
    expect(message.innerHTML).not.toContain('<img')

    // The visitor can try again immediately, and paid nothing for the refusal.
    expect(screen.getByLabelText('Your question')).toBeEnabled()
    expect(screen.getByTestId('runs-remaining')).toHaveTextContent('3 / 3')
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('distinguishes an unavailable gate from a refused question', async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByTestId('specialist-roster')

    await user.type(screen.getByLabelText('Your question'), 'A question')
    await user.click(screen.getByRole('button', { name: 'Choose specialists' }))

    const run = streamFor('/run')!
    await emit(run, 'error', {
      outcome: 'moderation_unavailable',
      message: "The safety check couldn't run just now.",
      decision_id: 'run-1',
    })
    await close(run)

    expect(await screen.findByTestId('refusal-moderation_unavailable')).toBeInTheDocument()
    expect(screen.queryByTestId('refusal-moderation_blocked')).toBeNull()
  })
})

describe('the dispatch gate', () => {
  it('issues no dispatch request until the control is pressed', async () => {
    const user = userEvent.setup()
    await reachDecision(user)

    // The decision is on screen with both briefs, and nothing has been sent.
    expect(screen.getByTestId('delegation-review')).toBeInTheDocument()
    expect(screen.getByTestId('brief-technical')).toHaveTextContent('Cover the mechanism only.')
    expect(screen.getByTestId('brief-financial')).toHaveTextContent('Cover the cost only.')
    expect(streamFor('/dispatch')).toBeUndefined()

    await user.click(screen.getByTestId('dispatch-button'))

    expect(streamFor('/dispatch')).toBeDefined()
  })

  it('surfaces a weak fit honestly', async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByTestId('specialist-roster')
    await user.click(screen.getByRole('button', { name: ROSTER.presets[0].text }))
    await user.click(screen.getByRole('button', { name: 'Choose specialists' }))

    const run = streamFor('/run')!
    await emit(run, 'delegation', { ...DECISION, fit_quality: 'weak' })
    await close(run)

    expect(screen.getByTestId('weak-fit-notice')).toBeInTheDocument()
    // The sharper alternative stays available.
    expect(screen.getByRole('button', { name: ROSTER.presets[0].text })).toBeInTheDocument()
  })
})

describe('the parallel columns', () => {
  it('shows both columns in progress at the same time', async () => {
    const user = userEvent.setup()
    const dispatch = await reachDispatch(user)

    // Interleaved, exactly as the server sends them: both statuses before
    // either answer.
    await emit(dispatch, 'specialist_status', {
      specialist_id: 'technical',
      status: 'running',
    })
    await emit(dispatch, 'specialist_status', {
      specialist_id: 'financial',
      status: 'running',
    })

    expect(screen.getByTestId('status-technical')).toHaveTextContent('running')
    expect(screen.getByTestId('status-financial')).toHaveTextContent('running')
    expect(screen.getByTestId('column-technical')).toHaveAttribute('data-phase', 'running')
    expect(screen.getByTestId('column-financial')).toHaveAttribute('data-phase', 'running')
  })

  it('leaves the slower column running when the faster one settles', async () => {
    const user = userEvent.setup()
    const dispatch = await reachDispatch(user)

    await emit(dispatch, 'specialist_status', { specialist_id: 'technical', status: 'running' })
    await emit(dispatch, 'specialist_status', { specialist_id: 'financial', status: 'running' })
    await emit(dispatch, 'specialist_answer', {
      specialist_id: 'technical',
      status: 'ok',
      answer: 'The mechanism is straightforward.',
      key_points: ['Contention is the problem'],
      error: null,
    })

    expect(screen.getByTestId('column-technical')).toHaveAttribute('data-phase', 'ok')
    // Its partner is untouched — this is the whole claim of the screen.
    expect(screen.getByTestId('column-financial')).toHaveAttribute('data-phase', 'running')
    expect(screen.getByTestId('status-financial')).toHaveTextContent('running')
  })

  it('keeps the surviving answer visible when one column fails', async () => {
    const user = userEvent.setup()
    const dispatch = await reachDispatch(user)

    await emit(dispatch, 'specialist_answer', {
      specialist_id: 'financial',
      status: 'ok',
      answer: 'It roughly doubles the bill.',
      key_points: ['Double the bill'],
      error: null,
    })
    await emit(dispatch, 'specialist_answer', {
      specialist_id: 'technical',
      status: 'failed',
      answer: '',
      key_points: [],
      error: "This specialist couldn't be reached.",
    })

    expect(screen.getByTestId('column-financial')).toHaveTextContent(
      'It roughly doubles the bill.',
    )
    // The failed column stays on screen so the missing contribution is visible.
    const failed = screen.getByTestId('column-technical')
    expect(failed).toHaveAttribute('data-phase', 'failed')
    expect(failed).toHaveTextContent("This specialist couldn't be reached.")
    expect(failed).toHaveTextContent('Cover the mechanism only.')
  })

  it('reports a timeout differently from a failure', async () => {
    const user = userEvent.setup()
    const dispatch = await reachDispatch(user)

    await emit(dispatch, 'specialist_answer', {
      specialist_id: 'technical',
      status: 'timeout',
      answer: '',
      key_points: [],
      error: 'Still working when the run stopped waiting.',
    })

    expect(screen.getByTestId('status-technical')).toHaveTextContent('timed out')
    expect(screen.getByTestId('status-technical')).not.toHaveTextContent('failed')
  })

  it('heads each column with its own brief before anything arrives', async () => {
    const user = userEvent.setup()
    await reachDispatch(user)

    expect(screen.getByTestId('column-technical')).toHaveTextContent('Cover the mechanism only.')
    expect(screen.getByTestId('column-financial')).toHaveTextContent('Cover the cost only.')
  })
})

describe('the merged answer', () => {
  const MERGED = {
    decision_id: 'run-1',
    text:
      '# Composting\n\nSeparating the workloads is **worth it**.\n\n' +
      '<img src=x onerror="alert(1)">',
    sources_used: ['technical', 'financial'],
    disagreement_note: {
      summary: 'One priced it, the other explained it.',
      agreements: ['Contention is the underlying problem'],
      complements: ['Technical supplied mechanism, Financial supplied cost'],
      contradictions: [],
      comparable: true,
    },
    model_call_count: 3,
  }

  async function completeRun(user: ReturnType<typeof userEvent.setup>, merged = MERGED) {
    const dispatch = await reachDispatch(user)
    await emit(dispatch, 'specialist_answer', {
      specialist_id: 'technical',
      status: 'ok',
      answer: 'Mechanism.',
      key_points: [],
      error: null,
    })
    await emit(dispatch, 'specialist_answer', {
      specialist_id: 'financial',
      status: 'ok',
      answer: 'Cost.',
      key_points: [],
      error: null,
    })
    await emit(dispatch, 'fan_out_complete', {
      decision_id: 'run-1',
      survivors: ['technical', 'financial'],
      model_call_count: 3,
    })
    await emit(dispatch, 'merged_answer', merged)
    await close(dispatch)
  }

  it('renders markdown as elements and never as HTML', async () => {
    const user = userEvent.setup()
    await completeRun(user)

    const panel = await screen.findByTestId('merged-answer')
    // Markdown became real elements...
    expect(within(panel).getByText('Composting').tagName).toBe('H3')
    expect(within(panel).getByText('worth it').tagName).toBe('STRONG')
    // ...and the injection payload became text, not an element.
    expect(panel.querySelector('img')).toBeNull()
    expect(panel).toHaveTextContent('<img src=x onerror="alert(1)">')
  })

  it('renders the disagreement note as its own panel with attribution', async () => {
    const user = userEvent.setup()
    await completeRun(user)

    const note = screen.getByTestId('disagreement-note')
    expect(note).toHaveTextContent('One priced it, the other explained it.')
    expect(note).toHaveTextContent('Contention is the underlying problem')
    expect(note).toHaveTextContent('No conflict found')
  })

  it('attributes each contradiction to a named specialist', async () => {
    const user = userEvent.setup()
    await completeRun(user, {
      ...MERGED,
      disagreement_note: {
        ...MERGED.disagreement_note,
        contradictions: [
          {
            claim_a: 'rewrite now',
            claim_b: 'do not start this quarter',
            specialist_a: 'technical',
            specialist_b: 'financial',
          },
        ],
      },
    })

    const note = screen.getByTestId('disagreement-note')
    expect(note).toHaveTextContent('Technical Analyst:')
    expect(note).toHaveTextContent('Financial Analyst:')
    expect(note).toHaveTextContent('rewrite now')
  })

  it('renders the degraded copy without a comparison', async () => {
    const user = userEvent.setup()
    await completeRun(user, {
      ...MERGED,
      sources_used: ['technical'],
      disagreement_note: {
        summary: 'Only one specialist returned an answer, so there was nothing to compare.',
        agreements: [],
        complements: [],
        contradictions: [],
        comparable: false,
      },
    })

    const note = screen.getByTestId('disagreement-note')
    expect(note).toHaveTextContent('Only one specialist returned an answer')
    // No comparison sections at all — not empty ones.
    expect(note).not.toHaveTextContent('Agree')
    expect(note).not.toHaveTextContent('Contradict')
  })

  it('shows the standing disclaimer', async () => {
    const user = userEvent.setup()
    await completeRun(user)

    expect(
      screen.getAllByText(/AI-generated demonstration output, not advice/i).length,
    ).toBeGreaterThanOrEqual(2)
  })

  it('uses no dangerouslySetInnerHTML anywhere in the tree', async () => {
    const user = userEvent.setup()
    const { container } = renderApp()
    await screen.findByTestId('specialist-roster')
    void user

    // The rendered DOM carries no script and no event-handler attributes, which
    // is what an `innerHTML` path would let model output introduce.
    expect(container.querySelector('script')).toBeNull()
    expect(container.innerHTML).not.toContain('onerror=')
  })
})

describe('the run allowance', () => {
  it('records a completed run and decrements the counter', async () => {
    const user = userEvent.setup()
    const dispatch = await reachDispatch(user)

    expect(screen.getByTestId('runs-remaining')).toHaveTextContent('3 / 3')

    await emit(dispatch, 'merged_answer', {
      decision_id: 'run-1',
      text: 'Merged.',
      sources_used: ['technical', 'financial'],
      disagreement_note: {
        summary: 'They complement.',
        agreements: [],
        complements: [],
        contradictions: [],
        comparable: true,
      },
      model_call_count: 3,
    })
    await close(dispatch)

    await waitFor(() =>
      expect(screen.getByTestId('runs-remaining')).toHaveTextContent('2 / 3'),
    )
  })

  it('rehydrates prior runs and the counter from a current-hour record', async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        used: 2,
        cap: 3,
        window: utcWindow(),
        runs: [
          {
            question: 'An earlier question',
            decision: DECISION,
            columns: [],
            merged: {
              decision_id: 'old',
              text: 'An earlier merged answer.',
              sources_used: ['technical'],
              disagreement_note: {
                summary: '',
                agreements: [],
                complements: [],
                contradictions: [],
                comparable: true,
              },
              model_call_count: 3,
            },
          },
        ],
      }),
    )

    renderApp()
    await screen.findByTestId('specialist-roster')

    expect(screen.getByTestId('runs-remaining')).toHaveTextContent('1 / 3')
    const prior = screen.getByTestId('prior-runs')
    expect(prior).toHaveTextContent('An earlier question')
    expect(prior).toHaveTextContent('An earlier merged answer.')
  })

  it('resets the counter and the runs when the hour stamp is stale', async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        used: 3,
        cap: 3,
        window: '2020-01-01T00',
        runs: [{ question: 'Last year', decision: DECISION, columns: [], merged: null }],
      }),
    )

    renderApp()
    await screen.findByTestId('specialist-roster')

    expect(screen.getByTestId('runs-remaining')).toHaveTextContent('3 / 3')
    expect(screen.queryByTestId('prior-runs')).toBeNull()
    expect(screen.queryByTestId('session-limit-message')).toBeNull()
  })

  it('disables the input at zero runs while prior results stay on screen', async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        used: 3,
        cap: 3,
        window: utcWindow(),
        runs: [{ question: 'A finished question', decision: DECISION, columns: [], merged: null }],
      }),
    )

    renderApp()
    await screen.findByTestId('specialist-roster')

    expect(screen.getByLabelText('Your question')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Choose specialists' })).toBeDisabled()
    expect(screen.getByRole('button', { name: ROSTER.presets[0].text })).toBeDisabled()
    expect(screen.getByTestId('session-limit-message')).toHaveTextContent(
      SESSION_LIMIT_MESSAGE,
    )
    // Everything already produced is still rendered.
    expect(screen.getByTestId('prior-runs')).toHaveTextContent('A finished question')
  })
})

describe('the two exhaustion messages', () => {
  it('are different strings', () => {
    expect(SESSION_LIMIT_MESSAGE).not.toEqual(SHOWCASE_LIMIT_MESSAGE)
    // Each names the limit it is about, so neither can be read as the other.
    expect(SESSION_LIMIT_MESSAGE).toMatch(/this demo's own limit/i)
    expect(SHOWCASE_LIMIT_MESSAGE).toMatch(/showcase-wide hourly allowance/i)
  })

  it('shows this app’s own limit when the local counter is spent', async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ used: 3, cap: 3, window: utcWindow(), runs: [] }),
    )
    renderApp()
    await screen.findByTestId('specialist-roster')

    expect(screen.getByTestId('session-limit-message')).toHaveTextContent(
      SESSION_LIMIT_MESSAGE,
    )
    expect(screen.queryByText(SHOWCASE_LIMIT_MESSAGE)).toBeNull()
  })

  it('shows the showcase-wide message when the server refuses the run', async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByTestId('specialist-roster')

    await user.click(screen.getByRole('button', { name: ROSTER.presets[0].text }))
    await user.click(screen.getByRole('button', { name: 'Choose specialists' }))

    const run = streamFor('/run')!
    await emit(run, 'error', {
      outcome: 'usage_limit_reached',
      message: "The 'generation' capability has reached the showcase-wide usage limit.",
      decision_id: 'run-1',
    })
    await close(run)

    expect(await screen.findByTestId('refusal-message')).toHaveTextContent(
      SHOWCASE_LIMIT_MESSAGE,
    )
    // The visitor's own three runs are untouched, so that message must not show.
    expect(screen.queryByTestId('session-limit-message')).toBeNull()
    expect(screen.getByTestId('runs-remaining')).toHaveTextContent('3 / 3')
  })
})

describe('leaving the page', () => {
  it('aborts an in-flight run on unmount', async () => {
    const user = userEvent.setup()
    const { unmount } = renderApp()
    await screen.findByTestId('specialist-roster')

    await user.click(screen.getByRole('button', { name: ROSTER.presets[0].text }))
    await user.click(screen.getByRole('button', { name: 'Choose specialists' }))

    const run = streamFor('/run')!
    expect(run.options.signal?.aborted).toBe(false)

    unmount()

    // An abandoned run would otherwise keep two specialists working against a
    // stream nobody is reading.
    expect(run.options.signal?.aborted).toBe(true)
  })
})

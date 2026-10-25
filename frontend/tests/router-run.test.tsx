// Built with Spec4 AI - https://spec4.ai
/**
 * The Router run view: the decision card, the five-run counter, and the
 * messages that tell this app's limit apart from the shared cap.
 *
 * Driven by a mocked event sequence, never a live backend. The counter is
 * spent only on `run_end`; a refused run costs nothing.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterRequestError, startRouterRun } from '../src/api/router'
import type { DecisionEvent, RouterRunEvent, StartRouterRunOptions } from '../src/api/router'
import { RouterApp } from '../src/apps/router/RouterApp'
import { STORAGE_KEY, utcWindow } from '../src/apps/router/runAllowance'
import {
  ROUTED_DECISION,
  ROUTED_END,
  routedRunEvents,
  routerFetch,
} from './routerFixtures'

vi.mock('../src/api/router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/api/router')>()
  return { ...actual, startRouterRun: vi.fn() }
})

const mockedRun = vi.mocked(startRouterRun)

function withProviders(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>
  )
}

/** Make the mocked run deliver these events, then resolve. */
function deliver(events: RouterRunEvent[]) {
  mockedRun.mockImplementation(async ({ onEvent }: StartRouterRunOptions) => {
    for (const event of events) {
      onEvent(event)
    }
  })
}

beforeEach(() => {
  window.localStorage.clear()
  mockedRun.mockReset()
  vi.stubGlobal('fetch', vi.fn().mockImplementation(routerFetch()))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function runPreset(name: RegExp) {
  const user = userEvent.setup()
  render(withProviders(<RouterApp />))
  await user.click(await screen.findByRole('button', { name: name }))
  await user.click(screen.getByRole('button', { name: 'Run' }))
  return user
}

describe('a routed preset run', () => {
  it('shows the decision card with all four scores and the agreement', async () => {
    deliver(routedRunEvents())
    await runPreset(/next crewed launch/)

    const card = await screen.findByTestId('decision-card')
    const scores = within(card).getByRole('list', { name: 'Route scores' })
    expect(within(scores).getAllByRole('listitem')).toHaveLength(4)
    expect(within(card).getByTestId('agreement')).toHaveTextContent('agreed with expected route')
    expect(within(card).getByText(/uncalibrated self-report/)).toBeInTheDocument()
    expect(screen.getByTestId('answer-route')).toHaveTextContent('via Search + generate')
    expect(screen.getByTestId('units')).toHaveTextContent('2 reserved · 1 used · 1 released')
    expect(screen.getByTestId('units')).toHaveTextContent('run time 1.23 s')
  })

  it('sends the preset id and its canonical text', async () => {
    deliver(routedRunEvents())
    await runPreset(/next crewed launch/)

    await screen.findByTestId('decision-card')
    const options = mockedRun.mock.calls[0][0]
    expect(options.presetId).toBe('p5')
    expect(options.request).toBe(
      'When is the next crewed launch to the International Space Station?',
    )
  })

  it('shows scores as 0–1 numbers, never percentages', async () => {
    deliver(routedRunEvents())
    await runPreset(/next crewed launch/)

    const scores = await screen.findByRole('list', { name: 'Route scores' })
    expect(within(scores).getByTestId('score-search_generation')).toHaveTextContent('0.93')
    expect(scores.textContent).not.toContain('%')
  })

  it('renders the rationale as plain text, not markup', async () => {
    const decision: DecisionEvent = { ...ROUTED_DECISION, rationale: '<b>bold</b> claim' }
    deliver(routedRunEvents(decision))
    await runPreset(/next crewed launch/)

    expect(await screen.findByTestId('rationale')).toHaveTextContent('<b>bold</b> claim')
    expect(screen.queryByText('bold', { selector: 'b' })).not.toBeInTheDocument()
  })

  it('drops the counter from 5 to 4 on run_end', async () => {
    deliver(routedRunEvents())
    render(withProviders(<RouterApp />))
    expect(await screen.findByTestId('runs-remaining')).toHaveTextContent('Runs left 5 of 5')

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /next crewed launch/ }))
    await user.click(screen.getByRole('button', { name: 'Run' }))

    await waitFor(() =>
      expect(screen.getByTestId('runs-remaining')).toHaveTextContent('Runs left 4 of 5'),
    )
  })

  it('does not spend a run on a stream that never ends', async () => {
    deliver(routedRunEvents().slice(0, 5))
    await runPreset(/next crewed launch/)

    await screen.findByTestId('decision-card')
    expect(screen.getByTestId('runs-remaining')).toHaveTextContent('Runs left 5 of 5')
  })
})

describe('history after a run', () => {
  it('shows the cost strip on the finished card and refetches the history', async () => {
    deliver(routedRunEvents())
    await runPreset(/next crewed launch/)

    expect(await screen.findByTestId('cost-strip')).toHaveTextContent('saved nothing')
    const historyCalls = () =>
      vi
        .mocked(fetch)
        .mock.calls.filter(([input]) => String(input).endsWith('/api/router/history')).length
    await waitFor(() => expect(historyCalls()).toBeGreaterThanOrEqual(2))
    expect(await screen.findByTestId('overall-rate')).toHaveTextContent('67%')
  })
})

describe('the low-confidence and malformed cards', () => {
  it('names both torn routes and the cost-order caveat', async () => {
    const decision: DecisionEvent = {
      ...ROUTED_DECISION,
      decision_kind: 'low_confidence',
      chosen_route: null,
      dispatched_route: 'retrieval',
      agreement: 'declined',
      low_confidence: {
        torn: ['retrieval', 'search_generation'],
        dispatched: 'retrieval',
        caveat:
          'The router was torn between RAG over the space dataset and Search + generate. The cheaper of the two was dispatched per the fixed cost order.',
      },
    }
    deliver(routedRunEvents(decision, { ...ROUTED_END, ending: 'low_confidence' }))
    await runPreset(/next crewed launch/)

    expect(await screen.findByRole('heading', { name: 'Low-confidence card' })).toBeInTheDocument()
    expect(screen.getByTestId('low-confidence-caveat')).toHaveTextContent('cheaper of the two')
    expect(screen.getByTestId('agreement')).toHaveTextContent('declined')
    const scores = screen.getByRole('list', { name: 'Route scores' })
    expect(within(scores).getAllByRole('listitem')).toHaveLength(4)
  })

  it('shows the malformed-decision note with no agreement statement', async () => {
    const decision: DecisionEvent = {
      ...ROUTED_DECISION,
      decision_kind: 'malformed',
      chosen_route: null,
      dispatched_route: 'single_call',
      scores: null,
      rationale: null,
      agreement: null,
      malformed_note: 'The router’s decision could not be read, so code sent it to single call.',
    }
    deliver(routedRunEvents(decision, { ...ROUTED_END, dispatched_route: 'single_call' }))
    await runPreset(/next crewed launch/)

    expect(await screen.findByTestId('malformed-note')).toHaveTextContent('could not be read')
    expect(screen.queryByTestId('agreement')).not.toBeInTheDocument()
  })
})

describe('refusals and limits', () => {
  it('names the shared cap on a shared-cap refusal, and costs no run', async () => {
    mockedRun.mockRejectedValue(
      new RouterRequestError(
        "The showcase's shared hourly allowance is too close to its cap. This is the gallery-wide cap, not this app's 5-run limit.",
        'shared_cap_reached',
      ),
    )
    await runPreset(/next crewed launch/)

    const alert = await screen.findByTestId('refusal')
    expect(alert).toHaveTextContent('Shared framework cap')
    expect(alert).toHaveTextContent('No run was used')
    expect(screen.getByTestId('runs-remaining')).toHaveTextContent('Runs left 5 of 5')
  })

  it('reports flagged free text without spending a run', async () => {
    mockedRun.mockRejectedValue(
      new RouterRequestError('That request was refused.', 'moderation_blocked'),
    )
    const user = userEvent.setup()
    render(withProviders(<RouterApp />))
    await user.type(await screen.findByLabelText(/type your own/), 'something unpleasant')
    await user.click(screen.getByRole('button', { name: 'Run' }))

    expect(await screen.findByTestId('refusal')).toHaveTextContent('refused by the safety check')
    expect(screen.getByTestId('runs-remaining')).toHaveTextContent('Runs left 5 of 5')
    expect(mockedRun.mock.calls[0][0].presetId).toBeUndefined()
  })

  it('disables input when the 5 runs are spent, naming that limit, with results kept', async () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        used: 5,
        cap: 5,
        window: utcWindow(),
        results: [
          {
            runId: 'run-old',
            request: 'An earlier request',
            presetId: null,
            decision: ROUTED_DECISION,
            answer: null,
            end: ROUTED_END,
          },
        ],
      }),
    )
    render(withProviders(<RouterApp />))

    expect(await screen.findByTestId('session-limit')).toHaveTextContent("this app's own 5-run limit")
    expect(screen.getByTestId('session-limit')).toHaveTextContent('not the showcase')
    expect(screen.getByRole('button', { name: 'Run' })).toBeDisabled()
    expect(screen.getByLabelText(/type your own/)).toBeDisabled()
    for (const button of within(screen.getByRole('list', { name: 'Preset requests' })).getAllByRole(
      'button',
    )) {
      expect(button).toBeDisabled()
    }
    expect(screen.getByText('An earlier request')).toBeInTheDocument()
    expect(screen.getByTestId('runs-remaining')).toHaveTextContent('Runs left 0 of 5')
  })
})

describe('the stream lifecycle', () => {
  it('aborts the stream on unmount', async () => {
    let signal: AbortSignal | null = null
    mockedRun.mockImplementation(async (options: StartRouterRunOptions) => {
      signal = options.signal
      await new Promise(() => {})
    })
    const user = userEvent.setup()
    const view = render(withProviders(<RouterApp />))
    await user.click(await screen.findByRole('button', { name: /next crewed launch/ }))
    await user.click(screen.getByRole('button', { name: 'Run' }))
    await waitFor(() => expect(signal).not.toBeNull())

    view.unmount()

    expect(signal!.aborted).toBe(true)
  })
})

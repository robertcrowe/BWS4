// Built with Spec4 AI - https://spec4.ai
/**
 * The comparison re-run in the UI: offered only on an eligible card, shown
 * beside the original with a zero router overhead, counted as one of the five
 * runs, and costing nothing when refused.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterRequestError, startRouterRerun, startRouterRun } from '../src/api/router'
import type {
  DecisionEvent,
  RouterRunEvent,
  RunEndEvent,
  StartRouterRerunOptions,
} from '../src/api/router'
import { RouterApp } from '../src/apps/router/RouterApp'
import type { StoredResult } from '../src/apps/router/runAllowance'
import { STORAGE_KEY, utcWindow } from '../src/apps/router/runAllowance'
import { ROUTED_DECISION, ROUTED_END, TEXT_ANSWER, routerFetch } from './routerFixtures'

vi.mock('../src/api/router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/api/router')>()
  return { ...actual, startRouterRun: vi.fn(), startRouterRerun: vi.fn() }
})

const mockedRun = vi.mocked(startRouterRun)
const mockedRerun = vi.mocked(startRouterRerun)

function withProviders(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>
  )
}

const MISROUTED: DecisionEvent = {
  ...ROUTED_DECISION,
  chosen_route: 'retrieval',
  dispatched_route: 'retrieval',
  agreement: 'misrouted',
}

function stored(overrides: Partial<StoredResult> = {}, end: Partial<RunEndEvent> = {}) {
  return {
    runId: 'run-orig',
    request: 'When is the next crewed launch to the International Space Station?',
    presetId: 'p5',
    decision: MISROUTED,
    answer: { ...TEXT_ANSWER, route: 'retrieval' as const, route_label: 'RAG over the space dataset' },
    end: { ...ROUTED_END, run_id: 'run-orig', dispatched_route: 'retrieval' as const, rerun_eligible: true, ...end },
    ...overrides,
  }
}

function seed(results: StoredResult[], used = results.length) {
  window.localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ used, cap: 5, window: utcWindow(), results }),
  )
}

const RERUN_EVENTS: RouterRunEvent[] = [
  {
    kind: 'run_started',
    run_id: 'run-re',
    request: 'When is the next crewed launch to the International Space Station?',
    preset_id: 'p5',
    units_reserved: 1,
    is_rerun: true,
    original_run_id: 'run-orig',
  },
  {
    kind: 'stage',
    stage: 'dispatching',
    message: 'Re-running through Search + generate (router skipped)',
  },
  { ...TEXT_ANSWER, text: 'The next crewed launch is in November [1].' },
  {
    ...ROUTED_END,
    run_id: 'run-re',
    units: { reserved: 1, used: 1, released: 0 },
    cost_strip: {
      ...ROUTED_END.cost_strip,
      overhead: { model_calls: 0, measured_ms: 0 },
      saved_nothing: false,
      notes: [],
    },
    is_rerun: true,
    original_run_id: 'run-orig',
  },
]

beforeEach(() => {
  window.localStorage.clear()
  mockedRun.mockReset()
  mockedRerun.mockReset()
  vi.stubGlobal('fetch', vi.fn().mockImplementation(routerFetch()))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the re-run offer', () => {
  it('appears on an eligible card', async () => {
    seed([stored()])
    render(withProviders(<RouterApp />))

    expect(await screen.findByRole('button', { name: 'Run it the expected way' })).toBeEnabled()
    expect(screen.getByText(/router overhead 0 · not counted in history/)).toBeInTheDocument()
  })

  it('does not appear on an agreed card', async () => {
    seed([stored({ decision: ROUTED_DECISION }, { rerun_eligible: false })])
    render(withProviders(<RouterApp />))

    await screen.findByTestId('decision-card')
    expect(screen.queryByRole('button', { name: 'Run it the expected way' })).not.toBeInTheDocument()
  })

  it('does not appear for free text', async () => {
    seed([stored({ presetId: null }, { rerun_eligible: false })])
    render(withProviders(<RouterApp />))

    await screen.findByTestId('decision-card')
    expect(screen.queryByRole('button', { name: 'Run it the expected way' })).not.toBeInTheDocument()
  })

  it('does not appear once the 5 runs are spent', async () => {
    seed([stored()], 5)
    render(withProviders(<RouterApp />))

    await screen.findByTestId('decision-card')
    expect(screen.queryByRole('button', { name: 'Run it the expected way' })).not.toBeInTheDocument()
  })
})

describe('running the comparison', () => {
  it('shows the re-run beside the original, overhead zero, and spends one run', async () => {
    seed([stored()])
    mockedRerun.mockImplementation(async ({ onEvent }: StartRouterRerunOptions) => {
      for (const event of RERUN_EVENTS) {
        onEvent(event)
      }
    })
    const user = userEvent.setup()
    render(withProviders(<RouterApp />))
    expect(await screen.findByTestId('runs-remaining')).toHaveTextContent('Runs left 4 of 5')

    await user.click(screen.getByRole('button', { name: 'Run it the expected way' }))

    const side = await screen.findByTestId('side-by-side')
    expect(within(side).getByText(/Original · RAG over the space dataset/)).toBeInTheDocument()
    const rerun = within(side).getByTestId('rerun-result')
    expect(rerun).toHaveTextContent('Expected way · Search + generate')
    expect(within(rerun).getByTestId('overhead')).toHaveTextContent('0 model calls · 0.00 s')
    expect(within(rerun).getByRole('columnheader', { name: /This re-run/ })).toBeInTheDocument()
    expect(screen.getByText(/does not feed the agreement or latency history/)).toBeInTheDocument()
    expect(screen.getByTestId('runs-remaining')).toHaveTextContent('Runs left 3 of 5')
    expect(screen.queryByRole('button', { name: 'Run it the expected way' })).not.toBeInTheDocument()

    const options = mockedRerun.mock.calls[0][0]
    expect(options.presetId).toBe('p5')
    expect(options.originalRunId).toBe('run-orig')
    expect(mockedRun).not.toHaveBeenCalled()
  })

  it('costs no run when the server refuses it', async () => {
    seed([stored()])
    mockedRerun.mockRejectedValue(
      new RouterRequestError('That run has already been re-run once.', 'rerun_already_used'),
    )
    const user = userEvent.setup()
    render(withProviders(<RouterApp />))

    await user.click(await screen.findByRole('button', { name: 'Run it the expected way' }))

    expect(await screen.findByTestId('refusal')).toHaveTextContent('already been re-run')
    await waitFor(() =>
      expect(screen.getByTestId('runs-remaining')).toHaveTextContent('Runs left 4 of 5'),
    )
  })
})

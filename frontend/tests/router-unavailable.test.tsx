// Built with Spec4 AI - https://spec4.ai
/**
 * The Router page while its route descriptions are not ready: a fixed
 * "temporarily unavailable" notice with a Retry button in place of the input.
 *
 * Mocked at `fetch`, never a live backend, so the presets wire mapping and the
 * retry call are exercised too. No run starts while unavailable, the counter
 * and the stored allowance entry are never touched, and a successful retry
 * restores the page in place.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RouterRequestError, startRouterRun } from '../src/api/router'
import { UNAVAILABLE_MESSAGE } from '../src/apps/router/RouterUnavailable'
import { STORAGE_KEY, utcWindow } from '../src/apps/router/runAllowance'
import { RouterScreen } from '../src/screens/router/RouterScreen'
import {
  HISTORY_WIRE,
  ROUTED_DECISION,
  ROUTED_END,
  ROUTER_PRESETS,
  UNAVAILABLE_PRESETS,
  presetsWireBody,
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

/** What the mocked backend does with `POST /api/router/retry`. */
type RetryBehaviour = 'succeed' | 'fail' | (() => Promise<Response>)

/**
 * A stateful backend stand-in: presets report unavailable until a retry
 * succeeds, after which they report ready, as the real holder does.
 */
function unavailableBackend(retry: RetryBehaviour) {
  let ready = false
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/router/history')) {
      return new Response(JSON.stringify(HISTORY_WIRE), { status: 200 })
    }
    if (url.endsWith('/api/router/retry')) {
      expect(init?.method).toBe('POST')
      if (typeof retry === 'function') {
        const response = await retry()
        ready = response.ok
        return response
      }
      if (retry === 'succeed') {
        ready = true
        return new Response(JSON.stringify({ available: true }), { status: 200 })
      }
      return new Response(
        JSON.stringify({
          detail: { code: 'descriptions_not_ready', message: 'A different server message.' },
        }),
        { status: 503 },
      )
    }
    const body = ready ? ROUTER_PRESETS : UNAVAILABLE_PRESETS
    return new Response(JSON.stringify(presetsWireBody(body)), { status: 200 })
  }
}

const fetchMock = vi.fn()

function retryCalls() {
  return fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/api/router/retry'))
    .length
}

/** An allowance entry with two runs spent and one stored result this hour. */
function seedAllowance(): string {
  const raw = JSON.stringify({
    used: 2,
    cap: 5,
    window: utcWindow(),
    results: [
      {
        runId: 'run-old',
        request: 'An earlier request',
        presetId: 'p5',
        decision: ROUTED_DECISION,
        answer: null,
        // Eligible for a re-run, so the test can check the offer is withheld.
        end: { ...ROUTED_END, run_id: 'run-old', rerun_eligible: true },
      },
    ],
  })
  window.localStorage.setItem(STORAGE_KEY, raw)
  return raw
}

beforeEach(() => {
  window.localStorage.clear()
  mockedRun.mockReset()
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the Router page while unavailable', () => {
  it('shows the message and Retry in place of the input, keeping the overview', async () => {
    fetchMock.mockImplementation(unavailableBackend('fail'))
    render(withProviders(<RouterScreen />))

    const notice = await screen.findByTestId('router-unavailable')
    expect(notice).toHaveTextContent('temporarily unavailable')
    expect(within(notice).getByRole('button', { name: 'Retry' })).toBeEnabled()

    expect(screen.getByTestId('router-overview')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'Router' })).toBeInTheDocument()
    expect(screen.queryByLabelText(/type your own/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Run' })).not.toBeInTheDocument()
    expect(screen.queryByRole('list', { name: 'Preset requests' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('route-descriptions-block')).not.toBeInTheDocument()
    expect(retryCalls()).toBe(0)
  })

  it('keeps stored results visible without offering their re-run', async () => {
    seedAllowance()
    fetchMock.mockImplementation(unavailableBackend('fail'))
    render(withProviders(<RouterScreen />))

    await screen.findByTestId('router-unavailable')
    expect(screen.getByText('An earlier request')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Run it the expected way' }),
    ).not.toBeInTheDocument()
  })
})

describe('the Retry button', () => {
  it('restores the input and knowledge panel on success, without a reload', async () => {
    fetchMock.mockImplementation(unavailableBackend('succeed'))
    const user = userEvent.setup()
    render(withProviders(<RouterScreen />))

    await user.click(await screen.findByRole('button', { name: 'Retry' }))

    expect(await screen.findByLabelText(/type your own/)).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Run' })).toBeInTheDocument()
    expect(screen.getByTestId('route-descriptions-block').textContent).toBe(
      ROUTER_PRESETS.routeDescriptionsBlock,
    )
    expect(screen.queryByTestId('router-unavailable')).not.toBeInTheDocument()
    expect(retryCalls()).toBe(1)
    expect(mockedRun).not.toHaveBeenCalled()
  })

  it('keeps the same message on failure, with no extra banner and no automatic retry', async () => {
    fetchMock.mockImplementation(unavailableBackend('fail'))
    const user = userEvent.setup()
    render(withProviders(<RouterScreen />))

    const before = (await screen.findByTestId('router-unavailable')).textContent
    await user.click(screen.getByRole('button', { name: 'Retry' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled())
    const notice = screen.getByTestId('router-unavailable')
    expect(notice.textContent).toBe(before)
    expect(notice).toHaveTextContent(UNAVAILABLE_MESSAGE)
    expect(screen.queryByText('A different server message.')).not.toBeInTheDocument()
    expect(screen.getAllByRole('alert')).toEqual([notice])
    expect(screen.queryByLabelText(/type your own/)).not.toBeInTheDocument()
    expect(retryCalls()).toBe(1)
  })

  it('is disabled while the retry is pending', async () => {
    let finish: (response: Response) => void = () => {}
    fetchMock.mockImplementation(
      unavailableBackend(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve
          }),
      ),
    )
    const user = userEvent.setup()
    render(withProviders(<RouterScreen />))

    await user.click(await screen.findByRole('button', { name: 'Retry' }))

    const pending = await screen.findByRole('button', { name: 'Retrying…' })
    expect(pending).toBeDisabled()
    finish(new Response(JSON.stringify({ available: true }), { status: 200 }))
    expect(await screen.findByLabelText(/type your own/)).toBeEnabled()
  })
})

describe('the runs-remaining counter', () => {
  it('is unchanged throughout, and the stored allowance is never written', async () => {
    const raw = seedAllowance()
    let attempts = 0
    fetchMock.mockImplementation(
      unavailableBackend(async () => {
        attempts += 1
        return attempts === 1
          ? new Response(JSON.stringify({ detail: { code: 'descriptions_not_ready' } }), {
              status: 503,
            })
          : new Response(JSON.stringify({ available: true }), { status: 200 })
      }),
    )
    const user = userEvent.setup()
    render(withProviders(<RouterScreen />))

    expect(await screen.findByTestId('runs-remaining')).toHaveTextContent('Runs left 3 of 5')

    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled())
    expect(screen.getByTestId('runs-remaining')).toHaveTextContent('Runs left 3 of 5')
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe(raw)

    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByLabelText(/type your own/)
    expect(screen.getByTestId('runs-remaining')).toHaveTextContent('Runs left 3 of 5')
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe(raw)
    expect(mockedRun).not.toHaveBeenCalled()
  })
})

describe('a run refused as not ready', () => {
  it('spends nothing and switches the page to its unavailable state', async () => {
    let presetsReads = 0
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/api/router/history')) {
        return new Response(JSON.stringify(HISTORY_WIRE), { status: 200 })
      }
      // Ready on the first read; the Router then becomes unavailable.
      presetsReads += 1
      const body = presetsReads === 1 ? ROUTER_PRESETS : UNAVAILABLE_PRESETS
      return new Response(JSON.stringify(presetsWireBody(body)), { status: 200 })
    })
    mockedRun.mockRejectedValue(
      new RouterRequestError('The Router is temporarily unavailable.', 'descriptions_not_ready'),
    )
    const user = userEvent.setup()
    render(withProviders(<RouterScreen />))

    await user.click(await screen.findByRole('button', { name: /next crewed launch/ }))
    await user.click(screen.getByRole('button', { name: 'Run' }))

    expect(await screen.findByTestId('router-unavailable')).toHaveTextContent(
      'temporarily unavailable',
    )
    expect(screen.getByTestId('runs-remaining')).toHaveTextContent('Runs left 5 of 5')
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull()
    expect(mockedRun).toHaveBeenCalledTimes(1)
  })
})

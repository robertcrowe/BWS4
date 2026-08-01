// Built with Spec4 AI - https://spec4.ai
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Plan, PlanningEvent } from '../src/api/planning'
import { fetchPlan, streamPlanningRun } from '../src/api/planning'
import { NavMenu } from '../src/components/NavMenu'
import { exampleApps } from '../src/data/example-apps'
import { PlanningScreen } from '../src/screens/planning/PlanningScreen'

vi.mock('@microsoft/fetch-event-source', () => ({ fetchEventSource: vi.fn() }))

const mockedFetchEventSource = vi.mocked(fetchEventSource)

const GOAL = { city: 'Lisbon', interests: 'street food' }

const PLAN: Plan = {
  goal: 'One day in Lisbon for street food',
  steps: [
    { index: 1, kind: 'research', description: 'Street food', search_query: 'street food Lisbon' },
    { index: 2, kind: 'synthesis', description: 'Compose the day', search_query: null },
  ],
  trimmed_note: null,
}

const PLAN_RESPONSE = {
  plan: PLAN,
  trimmed_note: null,
  replanned: false,
  model: 'groq/openai/gpt-oss-120b',
  calls_used: 1,
  call_ceiling: 7,
}

const PLAN_EVENT = { event: 'plan', data: JSON.stringify(PLAN) }

const STEP_EVENT = {
  event: 'step_result',
  data: JSON.stringify({
    step_index: 1,
    status: 'completed',
    summary: 'Found a food hall.',
    sources: [{ title: 'Time Out Market', url: 'https://a.test/1', snippet: 'A food hall.' }],
  }),
}

const ITINERARY_EVENT = {
  event: 'itinerary',
  data: JSON.stringify({
    city: 'Lisbon',
    blocks: [
      {
        time_of_day: 'morning',
        activity: 'Time Out Market',
        why_it_matches: 'food',
        source_refs: [1],
      },
    ],
  }),
}

/** Grab the options object the client handed to `fetchEventSource`. */
function lastCall() {
  const call = mockedFetchEventSource.mock.calls.at(-1)
  if (!call) {
    throw new Error('fetchEventSource was never called')
  }
  return { url: call[0] as string, init: call[1] }
}

/** Stub `fetch` for the plan endpoint, which is an ordinary request. */
function stubPlanFetch(body: unknown = PLAN_RESPONSE, ok = true) {
  const stub = vi.fn(async () =>
    new Response(JSON.stringify(body), { status: ok ? 200 : 503 }),
  )
  vi.stubGlobal('fetch', stub)
  return stub
}

beforeEach(() => {
  mockedFetchEventSource.mockReset()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the planning plan endpoint client', () => {
  it('posts the goal and returns the plan', async () => {
    const stub = stubPlanFetch()

    const response = await fetchPlan(GOAL)

    expect(stub).toHaveBeenCalledOnce()
    const [url, init] = stub.mock.calls[0] as [string, RequestInit]
    expect(url).toMatch(/\/api\/planning\/plan$/)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual(GOAL)
    expect(response.plan.steps).toHaveLength(2)
  })

  it('surfaces a rejected plan request with its code', async () => {
    stubPlanFetch({ code: 'usage_limit_reached', detail: 'Budget spent.' }, false)

    await expect(fetchPlan(GOAL)).rejects.toThrow('Budget spent.')
  })
})

describe('the planning SSE client', () => {
  it('starts the run with a POST body rather than a GET', async () => {
    // The reason this app cannot use the browser's native EventSource, which is
    // GET-only. If this regressed to a GET, the goal and the plan would have
    // nowhere to travel.
    mockedFetchEventSource.mockResolvedValue(undefined)

    await streamPlanningRun({ goal: GOAL, plan: PLAN, onEvent: vi.fn() })

    const { url, init } = lastCall()
    expect(url).toMatch(/\/api\/planning\/run$/)
    expect(init.method).toBe('POST')
  })

  it('sends the reviewed plan back as the advance signal', async () => {
    // The server keeps nothing between the two requests, so the plan the
    // visitor approved has to travel back with the go-ahead — otherwise the
    // run would execute something they never saw.
    mockedFetchEventSource.mockResolvedValue(undefined)

    await streamPlanningRun({ goal: GOAL, plan: PLAN, onEvent: vi.fn() })

    expect(JSON.parse(lastCall().init.body as string)).toEqual({ ...GOAL, plan: PLAN })
  })

  it('keeps the stream open when the tab is hidden', async () => {
    // fetch-event-source defaults `openWhenHidden` to false, which drops the
    // connection on a hidden tab and *reopens* it on return. Against an
    // endpoint that spends model and search quota, reopening means paying for
    // the run twice — silently, and only for visitors who switch tabs.
    mockedFetchEventSource.mockResolvedValue(undefined)

    await streamPlanningRun({ goal: GOAL, plan: PLAN, onEvent: vi.fn() })

    expect(lastCall().init.openWhenHidden).toBe(true)
  })

  it('surfaces each event as it arrives, in order', async () => {
    const received: PlanningEvent[] = []
    mockedFetchEventSource.mockImplementation(async (_url, init) => {
      init.onmessage?.({ id: '', ...PLAN_EVENT })
      init.onmessage?.({ id: '', ...STEP_EVENT })
      init.onmessage?.({ id: '', ...ITINERARY_EVENT })
    })

    await streamPlanningRun({
      goal: GOAL,
      plan: PLAN,
      onEvent: (event) => received.push(event),
    })

    expect(received.map((event) => event.name)).toEqual(['plan', 'step_result', 'itinerary'])
  })

  it('carries a categorised error event through as data, not as a throw', async () => {
    // The run answered 200 and kept its results; the failure travels alongside
    // them. Turning it into a rejection here would discard the partial output.
    const received: PlanningEvent[] = []
    mockedFetchEventSource.mockImplementation(async (_url, init) => {
      init.onmessage?.({ id: '', ...STEP_EVENT })
      init.onmessage?.({
        id: '',
        event: 'error',
        data: JSON.stringify({ code: 'synthesis_failed', message: 'Could not compose.' }),
      })
    })

    await streamPlanningRun({
      goal: GOAL,
      plan: PLAN,
      onEvent: (event) => received.push(event),
    })

    expect(received.map((event) => event.name)).toEqual(['step_result', 'error'])
  })

  it('ignores an event name it does not know', async () => {
    const received: PlanningEvent[] = []
    mockedFetchEventSource.mockImplementation(async (_url, init) => {
      init.onmessage?.({ id: '', event: 'ping', data: 'not json' })
      init.onmessage?.({ id: '', ...PLAN_EVENT })
    })

    await streamPlanningRun({
      goal: GOAL,
      plan: PLAN,
      onEvent: (event) => received.push(event),
    })

    expect(received.map((event) => event.name)).toEqual(['plan'])
  })

  it('makes a transport failure terminal instead of retrying forever', async () => {
    // fetch-event-source retries whenever `onerror` *returns*. On an endpoint
    // that spends quota, a silent retry loop against a backend that is down is
    // the worst available behaviour.
    mockedFetchEventSource.mockImplementation(async (_url, init) => {
      const outcome = init.onerror?.(new TypeError('Failed to fetch'))
      expect(outcome).toBeUndefined()
    })

    await expect(
      streamPlanningRun({ goal: GOAL, plan: PLAN, onEvent: vi.fn() }),
    ).rejects.toThrow(/Could not reach the backend/)
  })
})

describe('the planning screen and its directory entry', () => {
  it('renders at /planning', async () => {
    stubPlanFetch()
    const routing = createMemoryRouter([{ path: '/planning', element: <PlanningScreen /> }], {
      initialEntries: ['/planning'],
    })
    // The app's mutations need a query client, as every other example app's do.
    render(
      <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={routing} />
      </QueryClientProvider>,
    )

    expect(
      await screen.findByRole('heading', { name: 'Planning-Agent Example App', level: 1 }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /generate plan/i })).toBeInTheDocument()
  })

  it('explains the pattern exactly once, in the shared summary', async () => {
    // The screen renders `PatternSummary`; the app must not explain it again.
    // The content lives in example-apps.ts so the landing card and this screen
    // cannot describe the same pattern differently.
    stubPlanFetch()
    const routing = createMemoryRouter([{ path: '/planning', element: <PlanningScreen /> }], {
      initialEntries: ['/planning'],
    })
    render(
      <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={routing} />
      </QueryClientProvider>,
    )

    const explanations = await screen.findAllByLabelText(/About the .* pattern/)
    expect(explanations).toHaveLength(1)

    const summary = explanations[0]
    expect(summary).toHaveTextContent(/decompose a goal into a plan/i)
    expect(summary).toHaveTextContent(/one planner call plus up to three executor steps/i)
    expect(summary).toHaveTextContent(/any number of steps/i)
    expect(summary).toHaveTextContent(/not a limit of the pattern/i)
  })

  it('is appended after the machinery progression rather than slotted into it', () => {
    // The ordering rule in example-apps.ts: the first four ascend by machinery
    // required, and newer apps are appended after them. Asserted as "comes
    // after the fourth" rather than "is last", so the next app appended does
    // not have to edit this file to keep the rule true.
    const ids = exampleApps.map((app) => app.id)

    expect(ids.indexOf('planning_agent_example_app')).toBeGreaterThan(
      ids.indexOf('tool_use_integration'),
    )
  })

  it('is listed as live and routed to /planning', () => {
    const entry = exampleApps.find((app) => app.id === 'planning_agent_example_app')

    expect(entry?.status).toBe('live')
    expect(entry?.route).toBe('/planning')
  })

  it('is reachable from the header menu', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <NavMenu />
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: /menu/i }))

    expect(screen.getByRole('menuitem', { name: 'Planning-Agent Example App' })).toHaveAttribute(
      'href',
      '/planning',
    )
  })
})

// Built with Spec4 AI - https://spec4.ai
/**
 * The planning screen's three surfaces.
 *
 * `planning.test.tsx` covers the API clients and the SSE hook; this file covers
 * the UI built on them. The load-bearing test is the gate — no run request may
 * exist until the go-ahead is clicked — because that is the capability's whole
 * safeguard and it is the thing an ordinary refactor is most likely to break by
 * "helpfully" auto-advancing.
 */

import { fetchEventSource } from '@microsoft/fetch-event-source'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Plan } from '../src/api/planning'
import { PlanningApp } from '../src/apps/planning/PlanningApp'
import { gapNotes, stepStatuses } from '../src/apps/planning/planState'
import {
  RUN_CAP,
  isExhausted,
  readAllowance,
  runsRemaining,
  spendRun,
} from '../src/apps/planning/runAllowance'

vi.mock('@microsoft/fetch-event-source', () => ({ fetchEventSource: vi.fn() }))

const mockedFetchEventSource = vi.mocked(fetchEventSource)

const PLAN: Plan = {
  goal: 'One day in Lisbon for street food and modern art',
  steps: [
    {
      index: 1,
      kind: 'research',
      description: 'Find street food clusters',
      search_query: 'street food Lisbon',
    },
    {
      index: 2,
      kind: 'research',
      description: 'Find modern art venues',
      search_query: 'modern art Lisbon',
    },
    { index: 3, kind: 'synthesis', description: 'Compose the day', search_query: null },
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

function stepEvent(index: number, status: 'completed' | 'failed' = 'completed') {
  return {
    event: 'step_result',
    data: JSON.stringify({
      step_index: index,
      status,
      summary: status === 'failed' ? 'This step could not be completed.' : `Found things ${index}.`,
      sources:
        status === 'failed'
          ? []
          : [{ title: `Source ${index}`, url: `https://a.test/${index}`, snippet: 's' }],
    }),
  }
}

const ITINERARY_EVENT = {
  event: 'itinerary',
  data: JSON.stringify({
    city: 'Lisbon',
    blocks: [
      {
        time_of_day: 'morning',
        activity: 'Time Out Market',
        why_it_matches: 'street food',
        source_refs: [1],
      },
      {
        time_of_day: 'evening',
        activity: 'Wander Bairro Alto',
        why_it_matches: 'walkable',
        source_refs: [],
      },
    ],
  }),
}

/** Stub `fetch`, which serves the plan and retry endpoints. */
function stubFetch(body: unknown = PLAN_RESPONSE, ok = true) {
  const stub = vi.fn(async () => new Response(JSON.stringify(body), { status: ok ? 200 : 503 }))
  vi.stubGlobal('fetch', stub)
  return stub
}

function renderApp(element: ReactElement = <PlanningApp />) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}>{element}</QueryClientProvider>)
}

/** Fill the goal form and generate a plan. */
async function planFor(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('City'), 'Lisbon')
  await user.type(screen.getByLabelText('Interests'), 'street food, modern art')
  await user.click(screen.getByRole('button', { name: /generate plan/i }))
  return screen.findByTestId('plan-steps')
}

beforeEach(() => {
  mockedFetchEventSource.mockReset()
  window.localStorage.clear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('the run allowance', () => {
  it('starts at the full cap', () => {
    expect(readAllowance()).toEqual({ used: 0, cap: RUN_CAP })
    expect(runsRemaining(readAllowance())).toBe(RUN_CAP)
  })

  it('counts down as runs are spent, and reports exhaustion at the cap', () => {
    for (let index = 0; index < RUN_CAP; index += 1) {
      spendRun()
    }

    expect(isExhausted(readAllowance())).toBe(true)
    expect(runsRemaining(readAllowance())).toBe(0)
  })

  it('rolls over on a new UTC hour, like the server window it mirrors', () => {
    // A counter that only ever incremented would make the UI's stated reset
    // false on the one screen where the reset is the thing being explained.
    // The offsets here are hours: if the client silently reverted to a daily
    // window these would pass at midnight and fail the rest of the day.
    const noon = new Date('2026-07-30T12:00:00Z')
    spendRun(noon)
    expect(readAllowance(noon).used).toBe(1)

    const sameHour = new Date('2026-07-30T12:59:59Z')
    expect(readAllowance(sameHour).used).toBe(1)

    const nextHour = new Date('2026-07-30T13:00:00Z')
    expect(readAllowance(nextHour).used).toBe(0)
  })

  it('treats corrupt storage as a fresh allowance rather than breaking', () => {
    window.localStorage.setItem('planning_run_allowance', 'not json')

    expect(readAllowance()).toEqual({ used: 0, cap: RUN_CAP })
  })
})

describe('deriving step statuses', () => {
  it('marks the first unreported step running, and nothing after it', () => {
    // The backend runs steps strictly in order, so this is a true statement
    // rather than an animation.
    const statuses = stepStatuses(PLAN.steps, [], 'executing', null)

    expect(statuses).toEqual(['running', 'awaiting', 'awaiting'])
  })

  it('advances as results arrive', () => {
    const done = [
      { step_index: 1, status: 'completed' as const, summary: 's', sources: [] },
    ]

    expect(stepStatuses(PLAN.steps, done, 'executing', null)).toEqual([
      'completed',
      'running',
      'awaiting',
    ])
  })

  it('marks the synthesis step running only once every research step has reported', () => {
    // It emits no step_result of its own — its result is the itinerary — so it
    // cannot be judged by looking for a report that will never come.
    const both = [
      { step_index: 1, status: 'completed' as const, summary: 's', sources: [] },
      { step_index: 2, status: 'completed' as const, summary: 's', sources: [] },
    ]

    expect(stepStatuses(PLAN.steps, both, 'executing', null)).toEqual([
      'completed',
      'completed',
      'running',
    ])
  })

  it('keeps a failed step failed rather than letting it read as done', () => {
    const failed = [{ step_index: 1, status: 'failed' as const, summary: 's', sources: [] }]

    expect(stepStatuses(PLAN.steps, failed, 'executing', null)[0]).toBe('failed')
  })

  it('nothing is running before the go-ahead', () => {
    expect(stepStatuses(PLAN.steps, [], 'awaiting-goahead', null)).toEqual([
      'awaiting',
      'awaiting',
      'awaiting',
    ])
  })
})

describe('gap notes', () => {
  it('are empty for a run with no gaps', () => {
    const clean = [
      {
        step_index: 1,
        status: 'completed' as const,
        summary: 's',
        sources: [{ title: 't', url: 'u', snippet: 's' }],
      },
    ]
    const itinerary = {
      city: 'Lisbon',
      blocks: [
        { time_of_day: 'morning' as const, activity: 'a', why_it_matches: 'w', source_refs: [1] },
      ],
    }

    expect(gapNotes(clean, itinerary)).toEqual([])
  })

  it('name a failed step', () => {
    const failed = [{ step_index: 2, status: 'failed' as const, summary: 's', sources: [] }]

    expect(gapNotes(failed, null)[0]).toMatch(/step 2 did not complete/i)
  })

  it('distinguish a step that found nothing from one that failed', () => {
    // The search ran and the web had little to say. Reporting that as a failure
    // would tell the visitor the machinery broke.
    const empty = [{ step_index: 1, status: 'completed' as const, summary: 's', sources: [] }]

    expect(gapNotes(empty, null)[0]).toMatch(/found no usable results/i)
  })

  it('name an itinerary block that cites no research', () => {
    const itinerary = {
      city: 'Lisbon',
      blocks: [
        { time_of_day: 'evening' as const, activity: 'a', why_it_matches: 'w', source_refs: [] },
      ],
    }

    expect(gapNotes([], itinerary)[0]).toMatch(/evening block cites no research/i)
  })
})

describe('the goal form', () => {
  it('rejects a submission missing the city or the interests', async () => {
    const user = userEvent.setup()
    const stub = stubFetch()
    renderApp()

    await user.click(screen.getByRole('button', { name: /generate plan/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/both a city and your interests/i)
    expect(stub).not.toHaveBeenCalled()
  })

  it('shows the runs remaining', async () => {
    stubFetch()
    renderApp()

    expect(await screen.findByTestId('runs-remaining')).toHaveTextContent(
      `Runs remaining this hour: ${RUN_CAP} / ${RUN_CAP}`,
    )
  })

  it('disables submission at the cap and explains why', async () => {
    // The capability names visitor confusion at this exact moment as a
    // high-likelihood failure; a disabled button with no explanation causes it.
    for (let index = 0; index < RUN_CAP; index += 1) {
      spendRun()
    }
    stubFetch()
    renderApp()

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /generate plan/i })).toBeDisabled(),
    )
    expect(screen.getByRole('status')).toHaveTextContent(/unbounded by nature/i)
    expect(screen.getByRole('status')).toHaveTextContent(/resets at the top of the hour/i)
  })

  it('offers preset goals that fill both fields', async () => {
    const user = userEvent.setup()
    stubFetch()
    renderApp()

    await user.click(screen.getByRole('button', { name: /Tokyo — ramen/i }))

    expect(screen.getByLabelText('City')).toHaveValue('Tokyo')
    expect(screen.getByLabelText('Interests')).toHaveValue('ramen, temples, quiet gardens')
  })
})

describe('the plan review gate', () => {
  it('renders the plan with each step purpose and query before anything runs', async () => {
    const user = userEvent.setup()
    stubFetch()
    renderApp()

    const steps = await planFor(user)

    expect(within(steps).getByText('Find street food clusters')).toBeInTheDocument()
    expect(within(steps).getByText(/street food Lisbon/)).toBeInTheDocument()
    expect(within(steps).getAllByText(/awaiting go-ahead/i)).toHaveLength(3)
  })

  it('fires no run request until the go-ahead is clicked', async () => {
    // The capability's core safeguard. Auto-advancing after planning is the
    // named risk for this phase, and this is the assertion that catches it.
    const user = userEvent.setup()
    stubFetch()
    renderApp()

    await planFor(user)
    expect(mockedFetchEventSource).not.toHaveBeenCalled()

    mockedFetchEventSource.mockResolvedValue(undefined)
    await user.click(screen.getByRole('button', { name: /execute plan/i }))

    await waitFor(() => expect(mockedFetchEventSource).toHaveBeenCalledOnce())
  })

  it('spends a run only when execution starts, not when a plan is generated', async () => {
    // A plan the visitor walks away from costs nothing — the capability is
    // explicit that a run which executed no step does not consume allowance.
    const user = userEvent.setup()
    stubFetch()
    renderApp()

    await planFor(user)
    expect(screen.getByTestId('runs-remaining')).toHaveTextContent(`${RUN_CAP} / ${RUN_CAP}`)

    mockedFetchEventSource.mockResolvedValue(undefined)
    await user.click(screen.getByRole('button', { name: /execute plan/i }))

    await waitFor(() =>
      expect(screen.getByTestId('runs-remaining')).toHaveTextContent(`${RUN_CAP - 1} / ${RUN_CAP}`),
    )
  })

  it('shows the trim warning when the planner over-planned', async () => {
    const user = userEvent.setup()
    stubFetch({ ...PLAN_RESPONSE, trimmed_note: 'Two steps were dropped for budget.' })
    renderApp()

    await planFor(user)

    expect(screen.getByText('Two steps were dropped for budget.')).toBeInTheDocument()
  })
})

describe('the executing panel', () => {
  /** Plan, then execute, returning a function that pushes SSE events. */
  async function startRun(user: ReturnType<typeof userEvent.setup>) {
    let emit: ((message: { id: string; event: string; data: string }) => void) | undefined
    mockedFetchEventSource.mockImplementation(
      (_url, init) =>
        new Promise(() => {
          emit = (message) => init.onmessage?.(message)
        }),
    )

    await planFor(user)
    await user.click(screen.getByRole('button', { name: /execute plan/i }))
    await waitFor(() => expect(emit).toBeDefined())

    return emit!
  }

  it('renders each step result progressively as it arrives', async () => {
    const user = userEvent.setup()
    stubFetch()
    renderApp()

    const emit = await startRun(user)
    expect(screen.queryByTestId('step-results')).not.toBeInTheDocument()

    emit({ id: '', ...stepEvent(1) })
    expect(await screen.findByText('Step 1 result')).toBeInTheDocument()
    expect(screen.queryByText('Step 2 result')).not.toBeInTheDocument()

    emit({ id: '', ...stepEvent(2) })
    expect(await screen.findByText('Step 2 result')).toBeInTheDocument()
  })

  it('shows an in-progress indicator on the step currently executing', async () => {
    const user = userEvent.setup()
    stubFetch()
    renderApp()

    const emit = await startRun(user)

    const steps = screen.getByTestId('plan-steps')
    expect(within(steps).getAllByText(/running…/i)).toHaveLength(1)

    emit({ id: '', ...stepEvent(1) })
    await waitFor(() =>
      expect(within(screen.getByTestId('plan-steps')).getByText(/complete$/i)).toBeInTheDocument(),
    )
  })

  it('renders a failed step distinctly and keeps going', async () => {
    const user = userEvent.setup()
    stubFetch()
    renderApp()

    const emit = await startRun(user)
    emit({ id: '', ...stepEvent(1, 'failed') })
    emit({ id: '', ...stepEvent(2) })

    const results = await screen.findByTestId('step-results')
    expect(within(results).getByText('failed')).toBeInTheDocument()
    expect(within(results).getByText(/could not be completed/i)).toBeInTheDocument()
    expect(within(results).getByText('Step 2 result')).toBeInTheDocument()
  })

  it('renders the itinerary as morning/afternoon/evening blocks with their gaps named', async () => {
    const user = userEvent.setup()
    stubFetch()
    renderApp()

    const emit = await startRun(user)
    emit({ id: '', ...stepEvent(1) })
    emit({ id: '', ...ITINERARY_EVENT })

    const itinerary = await screen.findByTestId('itinerary')
    expect(within(itinerary).getByText('morning')).toBeInTheDocument()
    expect(within(itinerary).getByText('Time Out Market')).toBeInTheDocument()
    expect(within(itinerary).getByText(/from step 1 research/)).toBeInTheDocument()
    // The evening block cites nothing, and the UI says so rather than leaving
    // it looking as supported as the others.
    expect(within(itinerary).getByText(/no research behind this block/)).toBeInTheDocument()
    expect(within(screen.getByTestId('gap-notes')).getByText(/evening block cites no research/i))
      .toBeInTheDocument()
  })

  it('explains quota exhaustion without discarding what completed', async () => {
    const user = userEvent.setup()
    stubFetch()
    renderApp()

    const emit = await startRun(user)
    emit({ id: '', ...stepEvent(1) })
    emit({
      id: '',
      event: 'error',
      data: JSON.stringify({
        code: 'usage_limit_reached',
        message: 'Today’s shared budget is spent.',
        steps_completed: 1,
      }),
    })

    expect(await screen.findByText('Today’s shared budget is spent.')).toBeInTheDocument()
    // Scoped to the run notice: the overview card also mentions the reset, and
    // an unscoped query would pass on that instead of on the failure message.
    const notice = screen.getByRole('alert')
    expect(notice).toHaveTextContent(/resets at the top of the hour/i)
    expect(notice).toHaveTextContent(/never silently discards work/i)
    expect(screen.getByText('Step 1 result')).toBeInTheDocument()
  })

  it('offers a synthesis retry that keeps the research and costs no run', async () => {
    const user = userEvent.setup()
    const stub = stubFetch()
    renderApp()

    const emit = await startRun(user)
    emit({ id: '', ...stepEvent(1) })
    emit({
      id: '',
      event: 'error',
      data: JSON.stringify({
        code: 'synthesis_failed',
        message: 'The itinerary could not be composed.',
      }),
    })

    const retryButton = await screen.findByRole('button', { name: /retry synthesis only/i })
    const spentBefore = screen.getByTestId('runs-remaining').textContent

    stub.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          itinerary: {
            city: 'Lisbon',
            blocks: [
              {
                time_of_day: 'morning',
                activity: 'Composed on retry',
                why_it_matches: 'food',
                source_refs: [1],
              },
            ],
          },
        }),
        { status: 200 },
      ),
    )
    await user.click(retryButton)

    expect(await screen.findByText('Composed on retry')).toBeInTheDocument()
    expect(screen.getByTestId('runs-remaining')).toHaveTextContent(spentBefore!)
    expect(screen.getByText('Step 1 result')).toBeInTheDocument()
  })
})

describe('the plan endpoint failing', () => {
  it('explains a spent budget without offering a pointless retry', async () => {
    const user = userEvent.setup()
    stubFetch({ code: 'usage_limit_reached', detail: 'The daily planning budget is spent.' }, false)
    renderApp()

    await user.type(screen.getByLabelText('City'), 'Lisbon')
    await user.type(screen.getByLabelText('Interests'), 'food')
    await user.click(screen.getByRole('button', { name: /generate plan/i }))

    expect(await screen.findByText(/shared budget is spent/i)).toBeInTheDocument()
    expect(screen.getByText(/code: usage_limit_reached/)).toBeInTheDocument()
    expect(screen.queryByTestId('plan-steps')).not.toBeInTheDocument()
  })
})

describe('the pattern explanation', () => {
  it('is not duplicated inside the app', async () => {
    // It belongs to the screen, via the shared `PatternSummary`. Two copies of
    // it is a mistake this project has now made three times — single call,
    // chained calls, and here — so it is worth an assertion rather than an
    // eye.
    stubFetch()
    renderApp()

    expect(screen.queryByLabelText(/About the .* pattern/)).not.toBeInTheDocument()
    expect(screen.queryByText(/What is the planning-agent pattern/i)).not.toBeInTheDocument()
  })
})

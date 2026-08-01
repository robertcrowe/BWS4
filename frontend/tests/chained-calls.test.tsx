// Built with Spec4 AI - https://spec4.ai
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChainPlan, ChainResult } from '../src/api/chainedCalls'
import {
  ChainedCallsRequestError,
  FALLBACK_PLAN,
  fetchChainPlan,
  retryCritique,
  runChain,
} from '../src/api/chainedCalls'
import { ChainedCallsApp } from '../src/apps/chained-calls/ChainedCallsApp'
import { stepStatuses } from '../src/apps/chained-calls/chainState'
import { NavMenu } from '../src/components/NavMenu'
import { PatternSummary } from '../src/components/PatternSummary'
import { exampleApps } from '../src/data/example-apps'
import { router } from '../src/routes'
import { LandingScreen } from '../src/screens/landing/LandingScreen'

vi.mock('../src/api/chainedCalls', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../src/api/chainedCalls')>()),
  fetchChainPlan: vi.fn(),
  runChain: vi.fn(),
  retryCritique: vi.fn(),
}))

const mockedFetchPlan = vi.mocked(fetchChainPlan)
const mockedRunChain = vi.mocked(runChain)
const mockedRetryCritique = vi.mocked(retryCritique)

const PLAN: ChainPlan = {
  steps: [
    {
      position: 1,
      role: 'struggling_writer',
      label: 'Struggling Writer',
      description: 'Takes your story idea and drafts a short story in a self-doubting voice.',
    },
    {
      position: 2,
      role: 'harsh_critic',
      label: 'Harsh Critic',
      description: 'Receives that exact draft as its input and critiques it bluntly.',
    },
  ],
  chain_length: 2,
  length_note:
    'This demo runs exactly 2 chained calls per submission to conserve a shared ' +
    'budget. The pattern itself supports chains of any length.',
}

const STORY =
  'The lighthouse keeper found a bottle wedged in the rocks. He read it twice and threw it back.'

const COMPLETE: ChainResult = {
  status: 'complete',
  intermediate_output: {
    role: 'struggling_writer',
    title: "Maybe 'The Bottle'",
    text: STORY,
  },
  final_output: {
    role: 'harsh_critic',
    text: 'The only concrete image is abandoned immediately. The draft flinches from its material.',
    quoted_detail: 'a bottle wedged in the rocks',
  },
  quality_signal: { quoted_detail_found: true, match_ratio: 1, references_story: true },
  notice: null,
  writer_model: 'nvidia/nemotron-3-super-120b-a12b:free',
  critic_model: 'poolside/laguna-s-2.1:free',
}

const CRITIQUE_FAILED: ChainResult = {
  status: 'critique_failed',
  intermediate_output: COMPLETE.intermediate_output,
  final_output: null,
  quality_signal: null,
  notice:
    'The story was written, but the critic call did not complete. The draft below is unchanged.',
  writer_model: 'nvidia/nemotron-3-super-120b-a12b:free',
  critic_model: null,
}

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <ChainedCallsApp />
    </QueryClientProvider>,
  )
}

/** Render, then wait for the server's plan so the steps are settled. */
async function renderAppWithPlan() {
  const rendered = renderApp()
  await screen.findByText(PLAN.steps[0].description)
  return rendered
}

async function submitIdea(user: ReturnType<typeof userEvent.setup>, idea = 'a lighthouse keeper') {
  await user.type(screen.getByLabelText(/Story idea/i), idea)
  await user.click(screen.getByRole('button', { name: /Run chain/i }))
}

beforeEach(() => {
  mockedFetchPlan.mockReset()
  mockedRunChain.mockReset()
  mockedRetryCritique.mockReset()
  mockedFetchPlan.mockResolvedValue(PLAN)
})

describe('the chained-calls app before any submission', () => {
  it('describes what each of the two calls does', async () => {
    await renderAppWithPlan()

    // The feature's criterion is "told upfront ... before submitting a
    // request", so this asserts against a screen nobody has submitted on.
    expect(screen.getByText('Struggling Writer')).toBeInTheDocument()
    expect(screen.getByText(PLAN.steps[0].description)).toBeInTheDocument()
    expect(screen.getByText('Harsh Critic')).toBeInTheDocument()
    expect(screen.getByText(PLAN.steps[1].description)).toBeInTheDocument()

    expect(screen.queryByTestId('chain-result')).not.toBeInTheDocument()
  })

  it('still describes both calls when the backend has not answered', async () => {
    // This backend sleeps after ~15 minutes idle, so a first visitor routinely
    // arrives before the plan does. Showing nothing until it lands would fail
    // the upfront-description criterion exactly when it matters most.
    mockedFetchPlan.mockRejectedValue(new ChainedCallsRequestError('down', 'unreachable', 0))
    renderApp()

    expect(await screen.findByText('Struggling Writer')).toBeInTheDocument()
    expect(screen.getByText('Harsh Critic')).toBeInTheDocument()
  })

  it('shows the quota-conservation notice, saying two is the demo’s limit not the pattern’s', async () => {
    await renderAppWithPlan()

    const notice = screen.getByTestId('quota-notice')
    expect(notice).toHaveTextContent(/exactly 2 chained calls/i)
    expect(notice).toHaveTextContent(/any length/i)
  })

  it('explains the pattern once, from the shared directory', async () => {
    // The explanation belongs to `example-apps.ts` and reaches the screen
    // through `PatternSummary`, so the landing card and the screen say the same
    // thing. The app itself must not carry a second copy — the single-call
    // screen shipped with exactly that duplicate and had it removed.
    render(
      <MemoryRouter>
        <PatternSummary appId="chained_calls_example_app" />
      </MemoryRouter>,
    )

    expect(
      screen.getByText(/One call’s output becomes the next call’s input/i),
    ).toBeInTheDocument()

    await renderAppWithPlan()
    expect(screen.queryAllByText(/One call’s output becomes the next call’s input/i)).toHaveLength(
      1,
    )
  })

  it('does not submit an empty story idea', async () => {
    const user = userEvent.setup()
    await renderAppWithPlan()

    await user.click(screen.getByRole('button', { name: /Run chain/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/Enter a story idea/i)
    expect(mockedRunChain).not.toHaveBeenCalled()
  })
})

describe('a successful chain', () => {
  it('renders both output blocks, each labeled by the role that produced it', async () => {
    const user = userEvent.setup()
    mockedRunChain.mockResolvedValue(COMPLETE)
    await renderAppWithPlan()

    await submitIdea(user)

    const step1 = await screen.findByRole('heading', {
      name: /Step 1 · Struggling Writer \(intermediate output\)/i,
    })
    expect(step1).toBeInTheDocument()
    expect(screen.getByText(STORY)).toBeInTheDocument()

    expect(
      screen.getByRole('heading', { name: /Step 2 · Harsh Critic \(final output\)/i }),
    ).toBeInTheDocument()
    expect(screen.getByText(COMPLETE.final_output!.text)).toBeInTheDocument()
  })

  it('renders markdown in both the story and the critique', async () => {
    const user = userEvent.setup()
    mockedRunChain.mockResolvedValue({
      ...COMPLETE,
      intermediate_output: {
        ...COMPLETE.intermediate_output!,
        text: 'He read it *twice* and threw it back.',
      },
      final_output: {
        ...COMPLETE.final_output!,
        text: 'Two problems:\n\n- The image is abandoned\n- The ending flinches',
      },
    })
    await renderAppWithPlan()

    await submitIdea(user)

    // Emphasis a model chose inside a story is meaningful, not decoration.
    expect((await screen.findByText('twice')).tagName).toBe('EM')

    // Scoped to step 2: the screen's own step indicator is also a list, so an
    // unscoped count would pass without the critique rendering at all.
    const step2 = screen
      .getByRole('heading', { name: /Step 2 · Harsh Critic/i })
      .closest('section')!
    expect(within(step2).getAllByRole('listitem')).toHaveLength(2)
  })

  it('keeps a line break the writer put inside a paragraph', async () => {
    // Markdown collapses a single newline into a space. A story's own line
    // breaks are the writer's, so the renderer keeps them.
    const user = userEvent.setup()
    mockedRunChain.mockResolvedValue({
      ...COMPLETE,
      intermediate_output: {
        ...COMPLETE.intermediate_output!,
        text: 'He opened the door.\nThe cold came in.',
      },
    })
    await renderAppWithPlan()

    await submitIdea(user)

    const paragraph = await screen.findByText(/He opened the door\./)
    expect(paragraph.textContent).toBe('He opened the door.\nThe cold came in.')
    expect(paragraph.className).toContain('whitespace-pre-wrap')
  })

  it('shows the detail the critic took from the story', async () => {
    const user = userEvent.setup()
    mockedRunChain.mockResolvedValue(COMPLETE)
    await renderAppWithPlan()

    await submitIdea(user)

    // The visible evidence that call 2 read call 1's output rather than
    // writing commentary that would fit any story.
    expect(await screen.findByText('a bottle wedged in the rocks')).toBeInTheDocument()
    expect(screen.getByText(/Quoted detail found in the story above/i)).toBeInTheDocument()
  })

  it('says the overlap check does not judge whether the critique is right', async () => {
    const user = userEvent.setup()
    mockedRunChain.mockResolvedValue(COMPLETE)
    await renderAppWithPlan()

    await submitIdea(user)

    // A surface that asserts something must say what was actually checked.
    // "The quoted phrase is present" is not "the critique is correct".
    expect(await screen.findByText(/would take a third model call/i)).toBeInTheDocument()
  })

  it('sends only the story idea, once', async () => {
    const user = userEvent.setup()
    mockedRunChain.mockResolvedValue(COMPLETE)
    await renderAppWithPlan()

    await submitIdea(user, 'a small robot learning to paint')

    await waitFor(() => expect(mockedRunChain).toHaveBeenCalledTimes(1))
    expect(mockedRunChain.mock.calls[0][0]).toEqual({
      storyPrompt: 'a small robot learning to paint',
    })
    expect(mockedRetryCritique).not.toHaveBeenCalled()
  })

  it('clears the previous run before starting a new one', async () => {
    // The phase's named risk: an ephemeral result resurfacing against a
    // different prompt. Here it would be worse than stale — the critique on
    // screen would have been written about a story that is no longer there.
    const user = userEvent.setup()
    let release: (value: ChainResult) => void = () => {}
    mockedRunChain
      .mockResolvedValueOnce(COMPLETE)
      .mockImplementationOnce(() => new Promise((resolve) => (release = resolve)))
    await renderAppWithPlan()

    await submitIdea(user)
    expect(await screen.findByText(STORY)).toBeInTheDocument()

    await user.clear(screen.getByLabelText(/Story idea/i))
    await submitIdea(user, 'two rival vendors')

    await waitFor(() => expect(screen.queryByText(STORY)).not.toBeInTheDocument())
    expect(screen.queryByTestId('chain-result')).not.toBeInTheDocument()

    release(COMPLETE)
  })
})

describe('when the critic call fails', () => {
  it('keeps the intermediate output visible and offers a step-2-only retry', async () => {
    const user = userEvent.setup()
    mockedRunChain.mockResolvedValue(CRITIQUE_FAILED)
    await renderAppWithPlan()

    await submitIdea(user)

    // The story survives the failure — the whole point of the mitigation.
    expect(await screen.findByText(STORY)).toBeInTheDocument()
    expect(
      screen.getByRole('heading', { name: /Step 2 · Harsh Critic — failed/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Retry step 2 only/i })).toBeInTheDocument()
  })

  it('re-runs only the critic call, against the story already on screen', async () => {
    const user = userEvent.setup()
    mockedRunChain.mockResolvedValue(CRITIQUE_FAILED)
    mockedRetryCritique.mockResolvedValue(COMPLETE)
    await renderAppWithPlan()

    await submitIdea(user)
    await user.click(await screen.findByRole('button', { name: /Retry step 2 only/i }))

    await waitFor(() => expect(mockedRetryCritique).toHaveBeenCalledTimes(1))
    // Not a resubmission: the story is sent back unchanged, so the critique
    // that arrives is a critique of the draft the visitor is reading.
    expect(mockedRetryCritique.mock.calls[0][0]).toEqual({
      intermediateOutput: CRITIQUE_FAILED.intermediate_output,
    })
    expect(mockedRunChain).toHaveBeenCalledTimes(1)

    expect(
      await screen.findByRole('heading', { name: /Step 2 · Harsh Critic \(final output\)/i }),
    ).toBeInTheDocument()
    expect(screen.getByText(STORY)).toBeInTheDocument()
  })

  it('withholds the retry when the budget is spent, since retrying cannot succeed', async () => {
    const user = userEvent.setup()
    mockedRunChain.mockResolvedValue(CRITIQUE_FAILED)
    mockedRetryCritique.mockRejectedValue(
      new ChainedCallsRequestError('Budget spent.', 'usage_limit_reached', 503),
    )
    await renderAppWithPlan()

    await submitIdea(user)
    await user.click(await screen.findByRole('button', { name: /Retry step 2 only/i }))

    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /Retry step 2 only/i })).not.toBeInTheDocument(),
    )
    expect(screen.getByText(STORY)).toBeInTheDocument()
  })
})

describe('when the chain cannot start', () => {
  it('shows no partial output and no retry once the budget is spent', async () => {
    const user = userEvent.setup()
    mockedRunChain.mockRejectedValue(
      new ChainedCallsRequestError(
        'Today’s shared generation budget cannot cover all 2 calls in this chain.',
        'usage_limit_reached',
        503,
      ),
    )
    await renderAppWithPlan()

    await submitIdea(user)

    expect(await screen.findByText(/budget cannot cover both calls/i)).toBeInTheDocument()
    expect(screen.queryByTestId('chain-result')).not.toBeInTheDocument()
    // A spent budget resets at 00:00 UTC; a button guaranteed to fail is worse
    // than no button.
    expect(screen.queryByRole('button', { name: /Try again/i })).not.toBeInTheDocument()
  })

  it('offers a retry when the provider failed rather than the budget', async () => {
    const user = userEvent.setup()
    mockedRunChain.mockRejectedValue(
      new ChainedCallsRequestError('Every model failed.', 'generation_unavailable', 503),
    )
    await renderAppWithPlan()

    await submitIdea(user)

    // Two different operator problems must not be reported identically.
    expect(await screen.findByText(/The chain did not complete/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Try again/i })).toBeInTheDocument()
  })
})

describe('the step indicator', () => {
  it('does not claim to know when call 1 handed off to call 2', () => {
    // One round trip means the browser learns both calls finished at the same
    // instant. Animating the hand-off would be inventing an observation — the
    // theater the tool-use screen's fake progress bar was removed for.
    expect(stepStatuses('chain-running')).toEqual(['running', 'running'])
    // The retry path is genuinely granular: only one call is in flight.
    expect(stepStatuses('retry-running')).toEqual(['done', 'running'])
    expect(stepStatuses('complete')).toEqual(['done', 'done'])
    expect(stepStatuses('critique-failed')).toEqual(['done', 'failed'])
    expect(stepStatuses('idle')).toEqual(['pending', 'pending'])
    // Nothing ran, so nothing is marked as having run.
    expect(stepStatuses('blocked')).toEqual(['pending', 'pending'])
  })
})

describe('the bundled fallback plan', () => {
  it('names the same roles the wire types declare', () => {
    // The fallback is a second copy of the roles, so it needs pinning to the
    // first. These strings are also what the backend stamps on each block.
    expect(FALLBACK_PLAN.steps.map((step) => step.role)).toEqual([
      'struggling_writer',
      'harsh_critic',
    ])
    expect(FALLBACK_PLAN.chain_length).toBe(2)
    expect(FALLBACK_PLAN.length_note).toMatch(/any length/i)
  })
})

describe('reaching the app', () => {
  it('has a lazy route declared for /chained-calls', () => {
    const paths = router.routes.map((route) => route.path)
    expect(paths).toContain('/chained-calls')
  })

  it('is listed in the shared example-app directory as live', () => {
    const entry = exampleApps.find((app) => app.id === 'chained_calls_example_app')

    expect(entry?.status).toBe('live')
    expect(entry?.route).toBe('/chained-calls')
    expect(entry?.name).toMatch(/Chained-Calls/i)
  })

  it('appears on the landing page with a link that opens the screen', async () => {
    // Reads the *real* directory and the real LandingScreen. `landing.test.tsx`
    // mocks the directory to test the rendering rules; mocking it here would
    // make this a test of the mock rather than of the entry actually shipping.
    const user = userEvent.setup()
    const landingRouter = createMemoryRouter([
      { path: '/', element: <LandingScreen /> },
      { path: '/chained-calls', element: <p>Chained-calls screen opened.</p> },
    ])
    render(<RouterProvider router={landingRouter} />)

    const card = screen.getByText('Chained-Calls Example App')
    expect(card.closest('a')).toHaveAttribute('href', '/chained-calls')

    await user.click(card)
    expect(await screen.findByText('Chained-calls screen opened.')).toBeInTheDocument()
  })

  it('is reachable from the header menu on every screen', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <NavMenu />
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: /navigation menu/i }))

    expect(screen.getByRole('menuitem', { name: /Chained-Calls Example App/i })).toHaveAttribute(
      'href',
      '/chained-calls',
    )
  })

  it('reaches the landing page and the menu from one list, not two', async () => {
    // The landing_page failure-mode mitigation, as a behavioural assertion:
    // every menu entry must be an entry in the shared directory, so a sixth app
    // needs one edit rather than two. Phase 2 shipped a hand-maintained menu
    // entry for exactly one phase; a leftover would show up here as a menu item
    // the directory doesn't know about.
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <NavMenu />
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: /navigation menu/i }))

    const known = new Set(['Home', ...exampleApps.map((app) => app.name)])
    for (const item of screen.getAllByRole('menuitem')) {
      // Coming-soon items render as "<name> · soon".
      const label = (item.textContent ?? '').replace(/\s*·\s*soon\s*$/, '').trim()
      expect(known, `"${label}" is in the menu but not in example-apps.ts`).toContain(label)
    }
  })
})

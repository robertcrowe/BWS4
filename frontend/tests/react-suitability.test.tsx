// Built with Spec4 AI - https://spec4.ai
/**
 * The suitability advisory in the browser: a hint, and never a gate.
 *
 * **The load-bearing assertion is that Start is enabled for every verdict**,
 * including the discouraging ones and including the neutral state. The
 * capability's dominant risk is that "suitability check" reads like a
 * precondition — an implementation that disabled Start on `single_hop` would
 * look reasonable and would mean an upstream free-tier outage silently closes
 * the whole example. So the test is parametrised over every value the enum can
 * take plus `null`, and asserts the control stays live in all of them.
 *
 * The rest is what the capability's privacy section requires: the third-party
 * disclosure is present, and an over-length question is refused client-side
 * before a request is issued.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  MAX_QUESTION_CHARS,
  ReactRequestError,
  checkSuitability,
  fetchReactPresets,
  startReactRun,
} from '../src/api/react'
import type {
  QuestionSuitability,
  ReactPresetsResponse,
  SuitabilityResponse,
} from '../src/api/react'
import { ReactLoopApp } from '../src/apps/react/ReactLoopApp'

vi.mock('../src/api/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/api/react')>()
  return {
    ...actual,
    fetchReactPresets: vi.fn(),
    startReactRun: vi.fn(),
    checkSuitability: vi.fn(),
    fetchReactRun: vi.fn(),
  }
})

const mockedPresets = vi.mocked(fetchReactPresets)
const mockedCheck = vi.mocked(checkSuitability)
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

const MULTI_HOP = 'How old is the current CEO of the company that makes the Switch?'

function verdict(overrides: Partial<QuestionSuitability> = {}): QuestionSuitability {
  return {
    verdict: 'multi_hop_live',
    estimated_hops: 3,
    requires_live_info: true,
    live_hop_description: "the company's current CEO",
    exercises_loop: true,
    confidence: 'high',
    visitor_message: 'This needs three chained facts, one of them current.',
    ...overrides,
  }
}

function answered(response: SuitabilityResponse) {
  mockedCheck.mockResolvedValue(response)
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

/** Type a question and blur, which is where the check fires. */
async function typeAndBlur(text: string) {
  const user = userEvent.setup()
  const input = await screen.findByLabelText(/question \(or write your own\)/i)
  await user.click(input)
  await user.type(input, text)
  await user.tab()
  return user
}

beforeEach(() => {
  window.localStorage.clear()
  mockedPresets.mockReset()
  mockedPresets.mockResolvedValue(PRESETS)
  mockedCheck.mockReset()
  // A default, so a test that does not care about the advisory cannot leave the
  // mock returning `undefined` and blow up inside the component's `.then`.
  mockedCheck.mockResolvedValue({ verdict: null, checks_remaining: 5 })
  mockedRun.mockReset()
  mockedRun.mockImplementation(async () => {})
})

describe('the advisory is a hint, never a gate', () => {
  const cases: Array<[string, QuestionSuitability | null]> = [
    ['multi_hop_live', verdict()],
    [
      'multi_hop_static',
      verdict({
        verdict: 'multi_hop_static',
        requires_live_info: false,
        live_hop_description: null,
      }),
    ],
    [
      'single_hop',
      verdict({
        verdict: 'single_hop',
        estimated_hops: 1,
        requires_live_info: false,
        live_hop_description: null,
        exercises_loop: false,
      }),
    ],
    [
      'unanswerable',
      verdict({
        verdict: 'unanswerable',
        estimated_hops: 1,
        requires_live_info: false,
        live_hop_description: null,
        exercises_loop: false,
      }),
    ],
    ['unknown (the neutral state)', null],
  ]

  it.each(cases)('leaves Start enabled for %s', async (_name, value) => {
    // The whole point. A verdict that disabled Start would turn an upstream
    // outage into the example being closed.
    answered({ verdict: value, checks_remaining: 4 })
    renderApp()
    await typeAndBlur(MULTI_HOP)

    await waitFor(() => expect(mockedCheck).toHaveBeenCalled())

    expect(screen.getByRole('button', { name: /start run/i })).toBeEnabled()
  })

  it.each(cases)('renders an advisory for %s', async (_name, value) => {
    answered({ verdict: value, checks_remaining: 4 })
    renderApp()
    await typeAndBlur(MULTI_HOP)

    const testId =
      value === null ? 'react-suitability-unknown' : 'react-suitability-hint'
    expect(await screen.findByTestId(testId)).toBeInTheDocument()
  })

  it('says the visitor can run it anyway, even on a discouraging verdict', async () => {
    answered({
      verdict: verdict({
        verdict: 'single_hop',
        estimated_hops: 1,
        requires_live_info: false,
        live_hop_description: null,
        exercises_loop: false,
        visitor_message: 'One lookup answers this.',
      }),
      checks_remaining: 4,
    })
    renderApp()
    await typeAndBlur(MULTI_HOP)

    const hint = await screen.findByTestId('react-suitability-hint')
    expect(hint).toHaveAttribute('data-verdict', 'single_hop')
    expect(hint).toHaveTextContent(/only a suggestion — you can run it anyway/i)
  })

  it('hedges a low-confidence verdict rather than stating it flatly', async () => {
    answered({ verdict: verdict({ confidence: 'low' }), checks_remaining: 4 })
    renderApp()
    await typeAndBlur(MULTI_HOP)

    const hint = await screen.findByTestId('react-suitability-hint')
    expect(hint).toHaveTextContent(/not sure/i)
    expect(hint).toHaveTextContent(/low-confidence guess/i)
  })

  it('renders the neutral state as a note, not an error', async () => {
    answered({ verdict: null, checks_remaining: 0 })
    renderApp()
    await typeAndBlur(MULTI_HOP)

    const note = await screen.findByTestId('react-suitability-unknown')
    expect(note).toHaveTextContent(/couldn't assess this question up front/i)
    expect(note).not.toHaveAttribute('role', 'alert')
  })

  it('falls back to the neutral state when the check itself fails', async () => {
    mockedCheck.mockRejectedValue(new Error('the network is down'))
    renderApp()
    await typeAndBlur(MULTI_HOP)

    expect(await screen.findByTestId('react-suitability-unknown')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /start run/i })).toBeEnabled()
    // A transport failure is **not** a refusal. Showing one would tell the
    // visitor their question was rejected when nothing examined it — the same
    // distinction the server keeps between `blocked` and `unavailable`.
    expect(screen.queryByTestId('react-moderation-refusal')).toBeNull()
  })
})

describe('when the check fires', () => {
  it('fires on blur rather than on every keystroke', async () => {
    answered({ verdict: verdict(), checks_remaining: 4 })
    const user = userEvent.setup()
    renderApp()

    const input = await screen.findByLabelText(/question \(or write your own\)/i)
    await user.type(input, MULTI_HOP)

    // Still focused: nothing has been asked yet, despite ~60 keystrokes.
    expect(mockedCheck).not.toHaveBeenCalled()

    await user.tab()
    await waitFor(() => expect(mockedCheck).toHaveBeenCalledTimes(1))
  })

  it('does not re-ask for text it has already asked about', async () => {
    answered({ verdict: verdict(), checks_remaining: 4 })
    const user = userEvent.setup()
    renderApp()

    const input = await screen.findByLabelText(/question \(or write your own\)/i)
    await user.click(input)
    await user.type(input, MULTI_HOP)
    await user.tab()
    await waitFor(() => expect(mockedCheck).toHaveBeenCalledTimes(1))

    await user.click(input)
    await user.tab()
    expect(mockedCheck).toHaveBeenCalledTimes(1)
  })

  it('never fires for a curated preset', async () => {
    // Presets are pre-vetted: they skip the gate and the advisory alike, and
    // spending a check on one would be paying for an answer already known.
    const user = userEvent.setup()
    renderApp()

    await user.click(await screen.findByRole('button', { name: /newest UN member/i }))
    await user.click(screen.getByRole('button', { name: /start run/i }))

    expect(mockedCheck).not.toHaveBeenCalled()
  })

  it('clears a stale advisory when the question changes', async () => {
    answered({ verdict: verdict(), checks_remaining: 4 })
    const user = userEvent.setup()
    renderApp()

    const input = await screen.findByLabelText(/question \(or write your own\)/i)
    await user.click(input)
    await user.type(input, MULTI_HOP)
    await user.tab()
    await screen.findByTestId('react-suitability-hint')

    await user.click(input)
    await user.type(input, ' and more')

    // The advisory belonged to the previous text.
    expect(screen.queryByTestId('react-suitability-hint')).toBeNull()
  })
})

describe('the privacy and length requirements', () => {
  it('shows the third-party disclosure notice', async () => {
    renderApp()

    const notice = await screen.findByTestId('react-disclosure')
    expect(notice).toHaveTextContent(/sent to a third-party model provider/i)
    expect(notice).toHaveTextContent(/web search provider/i)
    expect(notice).toHaveTextContent(/don't enter personal or confidential/i)
  })

  it('rejects an over-length question client-side before any request', async () => {
    const user = userEvent.setup()
    renderApp()

    const input = await screen.findByLabelText(/question \(or write your own\)/i)
    await user.click(input)
    // `maxLength` stops the field one over the cap, which is what trips the
    // client-side guard without needing to paste an essay.
    await user.paste('x'.repeat(MAX_QUESTION_CHARS + 50))

    expect(screen.getByTestId('react-too-long')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /start run/i })).toBeDisabled()

    await user.tab()
    expect(mockedRun).not.toHaveBeenCalled()
    // And no check was spent on text that cannot be run.
    expect(mockedCheck).not.toHaveBeenCalled()
  })

  it('shows a live character count', async () => {
    const user = userEvent.setup()
    renderApp()

    const input = await screen.findByLabelText(/question \(or write your own\)/i)
    await user.type(input, 'abc')

    expect(screen.getByTestId('react-char-count')).toHaveTextContent(
      `3/${MAX_QUESTION_CHARS}`,
    )
  })
})

describe('a moderation refusal', () => {
  it('is shown as a refusal, never as an advisory', async () => {
    mockedCheck.mockRejectedValue(
      new ReactRequestError('That question cannot be run here.', 'moderation_blocked'),
    )
    renderApp()
    await typeAndBlur(MULTI_HOP)

    const refusal = await screen.findByTestId('react-moderation-refusal')
    expect(refusal).toHaveTextContent('That question cannot be run here.')
    expect(screen.queryByTestId('react-suitability-hint')).toBeNull()
    expect(screen.queryByTestId('react-suitability-unknown')).toBeNull()
  })

  it('distinguishes an unavailable gate from a blocked question', async () => {
    mockedCheck.mockRejectedValue(
      new ReactRequestError(
        'Nothing could check that question just now.',
        'moderation_unavailable',
      ),
    )
    renderApp()
    await typeAndBlur(MULTI_HOP)

    expect(await screen.findByTestId('react-moderation-refusal')).toHaveTextContent(
      /nothing could check/i,
    )
  })
})

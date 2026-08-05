// Built with Spec4 AI - https://spec4.ai
/**
 * The /react route: that it exists once, in both places, and opens.
 *
 * The phase's third named trap is roster/navigation drift — an app added to the
 * landing directory and to the hamburger menu as two separate edits, leaving it
 * discoverable in one place and not the other. The shared `example-apps.ts`
 * makes that structurally impossible, and these assertions are what keep it
 * that way: **exactly once** in each surface, from one entry, plus a
 * navigation that actually lands on the screen.
 *
 * `routes.test.tsx` already pins catalogue/router set equality in both
 * directions, so this file does not repeat it. What is here is the rendered
 * result a visitor would see.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchReactPresets } from '../src/api/react'
import type { ReactPresetsResponse } from '../src/api/react'
import { NavMenu } from '../src/components/NavMenu'
import { exampleApps } from '../src/data/example-apps'
import { LandingScreen } from '../src/screens/landing/LandingScreen'
import { ReactLoopScreen } from '../src/screens/react/ReactLoopScreen'

vi.mock('../src/api/react', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/api/react')>()
  return { ...actual, fetchReactPresets: vi.fn() }
})

const mockedPresets = vi.mocked(fetchReactPresets)

const PRESETS: ReactPresetsResponse = {
  setVersion: 'v1',
  cycleBudget: 8,
  presets: [
    {
      id: 'p1',
      label: 'Highest mountain in the newest UN member',
      question:
        'How tall is the highest mountain in the country that most recently joined the United Nations?',
      hopCount: 2,
      guaranteedFullyObserved: true,
    },
    {
      id: 'p2',
      label: "Coach of the reigning Women's World Cup winners",
      question:
        "Who is the current head coach of the national team that won the most recent FIFA Women's World Cup?",
      hopCount: 2,
      guaranteedFullyObserved: true,
    },
    {
      id: 'p3',
      label: "Population of a Nobel laureate's birthplace",
      question:
        'What is the population of the birthplace of the most recent Nobel laureate in Literature?',
      hopCount: 3,
      guaranteedFullyObserved: true,
    },
    {
      id: 'p4',
      label: "Current employer of the Transformer paper's lead author",
      question:
        'Which company currently employs the lead author of the paper that introduced the Transformer architecture?',
      hopCount: 2,
      guaranteedFullyObserved: false,
    },
    {
      id: 'p5',
      label: "Tallest building in a famous director's birthplace",
      question: 'What is the tallest building in the birthplace of the director of Spirited Away?',
      hopCount: 2,
      guaranteedFullyObserved: false,
    },
  ],
}

function withQuery(ui: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
}

function renderScreen() {
  return render(
    withQuery(
      <MemoryRouter>
        <ReactLoopScreen />
      </MemoryRouter>,
    ),
  )
}

describe('the ReAct Loop catalogue entry', () => {
  it('exists exactly once in the shared directory', () => {
    const entries = exampleApps.filter((app) => app.id === 'react_loop_example_app')

    expect(entries).toHaveLength(1)
    expect(entries[0].status).toBe('live')
    expect(entries[0].route).toBe('/react')
  })

  it('is appended last rather than slotted into the machinery progression', () => {
    // The catalogue's ordering rule is newest-last: the first four ascend by
    // machinery required and everything after them is appended in the order it
    // shipped. Inserting here would reshuffle the landing cards *and* the menu.
    expect(exampleApps.at(-1)?.id).toBe('react_loop_example_app')
  })

  it('appears exactly once on the landing roster, as a live link', () => {
    render(
      withQuery(
        <MemoryRouter>
          <LandingScreen />
        </MemoryRouter>,
      ),
    )

    const links = screen.getAllByRole('link', { name: /ReAct-Loop Example App/i })

    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute('href', '/react')
  })

  it('appears exactly once in the hamburger navigation', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <NavMenu />
      </MemoryRouter>,
    )

    await user.click(screen.getByRole('button', { name: /open navigation menu/i }))
    const menu = screen.getByRole('menu')

    const links = within(menu).getAllByRole('menuitem', { name: /ReAct-Loop Example App/i })
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute('href', '/react')
  })

  it('opens the ReAct screen when selected from the navigation', async () => {
    const user = userEvent.setup()
    render(
      withQuery(
        <MemoryRouter initialEntries={['/']}>
          <NavMenu />
          <Routes>
            <Route path="/" element={<p>landing stand-in</p>} />
            <Route path="/react" element={<ReactLoopScreen />} />
          </Routes>
        </MemoryRouter>,
      ),
    )

    await user.click(screen.getByRole('button', { name: /open navigation menu/i }))
    await user.click(screen.getByRole('menuitem', { name: /ReAct-Loop Example App/i }))

    expect(
      screen.getByRole('heading', { level: 1, name: /ReAct-Loop Example App/i }),
    ).toBeInTheDocument()
  })
})

describe('the /react screen', () => {
  beforeEach(() => {
    mockedPresets.mockReset()
    mockedPresets.mockResolvedValue(PRESETS)
  })

  it('renders the pattern summary from the shared catalogue', async () => {
    renderScreen()

    expect(await screen.findByText(/interleaves reasoning and acting/i)).toBeInTheDocument()
  })

  it('populates the selector from the presets endpoint rather than a local copy', async () => {
    renderScreen()

    await screen.findByRole('button', { name: /newest UN member/i })
    const chips = screen.getByTestId('react-preset-chips')

    expect(within(chips).getAllByRole('button')).toHaveLength(5)
    expect(mockedPresets).toHaveBeenCalled()
  })

  it('shows the chosen preset question verbatim', async () => {
    const user = userEvent.setup()
    renderScreen()

    await user.click(await screen.findByRole('button', { name: /Nobel laureate/i }))

    expect(await screen.findByTestId('react-selected-question')).toHaveTextContent(
      'What is the population of the birthplace of the most recent Nobel laureate in Literature?',
    )
  })

  it('accepts free-form text rather than disabling the input', async () => {
    const user = userEvent.setup()
    renderScreen()

    const input = await screen.findByLabelText(/question \(or write your own\)/i)
    expect(input).toBeEnabled()

    await user.type(input, 'Who won?')
    expect(input).toHaveValue('Who won?')
  })

  it('sends one question source, never both', async () => {
    const user = userEvent.setup()
    renderScreen()

    const input = await screen.findByLabelText(/question \(or write your own\)/i)
    await user.type(input, 'my own question')
    await user.click(screen.getByRole('button', { name: /Nobel laureate/i }))

    expect(input).toHaveValue('')
  })

  it('offers no control to change the server-fixed budget', async () => {
    // The mock draws a 3-6 cycle-budget select. It is deliberately not built:
    // the budget is server-fixed, and the run reserves its whole worst case up
    // front, so a control that appeared to set it would do nothing.
    renderScreen()

    await screen.findByRole('button', { name: /newest UN member/i })

    expect(screen.queryByRole('combobox')).toBeNull()
    expect(screen.getByText(/up to 8 searches \+ 1 answer call/i)).toBeInTheDocument()
  })

  it('shows the runs-remaining indicator before any run', async () => {
    renderScreen()

    expect(await screen.findByTestId('react-runs-remaining')).toHaveTextContent(
      '2 of 2 runs remaining',
    )
  })

  it('surfaces a preset-fetch failure instead of rendering an empty selector', async () => {
    mockedPresets.mockRejectedValue(
      new Error('Could not reach the backend at /api/react/presets.'),
    )
    renderScreen()

    await waitFor(() => {
      expect(screen.getByText(/could not reach the backend/i)).toBeInTheDocument()
    })
  })
})

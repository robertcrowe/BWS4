// Built with Spec4 AI - https://spec4.ai
/**
 * The /collab route: what a visitor can see today, and what they must not.
 *
 * Two things are worth stating about what is asserted here.
 *
 * The candid single-owner note is checked by *content*, not by the presence of
 * a panel. The feature spec names "visitors take the staged trust boundary as a
 * genuine cross-organisation deployment" as a failure mode with prominent
 * placement as its mitigation, so a test that only counted panels would pass
 * against a screen that had quietly dropped the sentence.
 *
 * This file covers the *static* half of the screen — overview, identity cards,
 * catalogue and nav registration. The negotiation run has its own file,
 * `collab-run.test.tsx`, because its properties are about a stream rather than
 * a render.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, RouterProvider, createMemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchIdentityCards } from '../src/api/collab'
import type { IdentityCardsResponse } from '../src/api/collab'
import { CollabScreen } from '../src/screens/collab/CollabScreen'
import { LandingScreen } from '../src/screens/landing/LandingScreen'
import { NavMenu } from '../src/components/NavMenu'
import { exampleApps } from '../src/data/example-apps'

vi.mock('../src/api/collab', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../src/api/collab')>()
  return { ...actual, fetchIdentityCards: vi.fn() }
})

const mockedFetch = vi.mocked(fetchIdentityCards)

function card(id: string, role: string, name: string) {
  return {
    id,
    role,
    color: '#38bdf8',
    card: {
      name,
      description: `${name} does its job.`,
      version: '1.0.0',
      protocolVersion: '0.3.0',
      url: null,
      provider: { organization: 'BWS4 · Spec4 reference agent', url: 'https://spec4.ai' },
      capabilities: {
        streaming: false,
        pushNotifications: false,
        stateTransitionHistory: false,
      },
      skills: [
        { id: 'quoting', name: 'Quoting', description: 'Prices a request.', tags: [], examples: [] },
      ],
      toolAccess: 'none',
      defaultInputModes: ['application/json'],
      defaultOutputModes: ['application/json'],
    },
  }
}

const CARDS: IdentityCardsResponse = {
  agents: [
    card('buyer', 'buyer', 'Buyer Agent "Procura"'),
    card('northwind', 'seller', 'Seller Agent "Northwind Supply"'),
    card('meridian', 'seller', 'Seller Agent "Meridian Trading"'),
  ],
}

function renderScreen() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CollabScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the /collab screen', () => {
  beforeEach(() => {
    mockedFetch.mockReset()
    mockedFetch.mockResolvedValue(CARDS)
  })

  it('renders the pattern overview and contrasts it with orchestrated subagents', async () => {
    renderScreen()

    expect(
      await screen.findByRole('heading', { name: /Multi-Agent Collaboration Example App/i }),
    ).toBeInTheDocument()
    // The contrast comes from the shared PatternSummary, rendered on this
    // screen — matched on content rather than on a testid, so dropping the
    // summary would fail here rather than pass quietly.
    expect(screen.getByText(/orchestrated subagents/i)).toBeInTheDocument()
    expect(screen.getByText(/peers rather than workers/i)).toBeInTheDocument()
  })

  it('states that the A2A data model is used without its network transport', () => {
    renderScreen()

    const overview = screen.getByTestId('collab-overview')
    expect(overview).toHaveTextContent(/without its network transport/i)
    expect(overview).toHaveTextContent(/well-known\/agent-card\.json/i)
    expect(overview).toHaveTextContent(/authentication between owners/i)
  })

  it('carries the candid single-owner note, not as a footnote', () => {
    renderScreen()

    const overview = screen.getByTestId('collab-overview')
    expect(overview).toHaveTextContent(/one BWS4 repository under one owner/i)
    expect(overview).toHaveTextContent(/staged for teaching/i)
    expect(overview).toHaveTextContent(/over-engineering in a real system/i)
  })

  it('states the per-run call budget', () => {
    renderScreen()

    expect(screen.getByTestId('collab-overview')).toHaveTextContent(/6 model calls/i)
  })

  it('renders the three identity cards', async () => {
    renderScreen()

    expect(await screen.findByTestId('agent-card-buyer')).toBeInTheDocument()
    expect(screen.getByTestId('agent-card-northwind')).toBeInTheDocument()
    expect(screen.getByTestId('agent-card-meridian')).toBeInTheDocument()
  })

  it('fetches the cards rather than hardcoding them', async () => {
    renderScreen()

    await screen.findByTestId('agent-card-buyer')
    expect(mockedFetch).toHaveBeenCalledTimes(1)
  })

  it('expands a card to show provider, skills and the no-tool-access line', async () => {
    const user = userEvent.setup()
    renderScreen()

    const panel = await screen.findByTestId('agent-card-northwind')
    const toggle = within(panel).getByRole('button')

    // Collapsed by default, per the surface's two states.
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    await user.click(toggle)

    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(panel).toHaveTextContent(/BWS4 · Spec4 reference agent/)
    expect(panel).toHaveTextContent(/Quoting/)
    expect(panel).toHaveTextContent(/knowledge and messages only/i)
  })

  it('shows an error rather than an empty panel when the cards cannot be loaded', async () => {
    mockedFetch.mockRejectedValue(new Error('Could not reach the backend at /api/collab.'))
    renderScreen()

    expect(await screen.findByText(/Could not reach the backend/i)).toBeInTheDocument()
  })

  it('renders the static overview even while the cards are still loading', () => {
    mockedFetch.mockReturnValue(new Promise(() => {}))
    renderScreen()

    // The overview needs no network call, so a slow backend must not hide it.
    expect(screen.getByTestId('collab-overview')).toHaveTextContent(/staged for teaching/i)
  })

  it('accepts only closed choices, never free text', async () => {
    // This replaced a Phase 1 assertion that there were *no* negotiation
    // controls, which Phase 4 correctly made obsolete by adding them. What is
    // permanent is the property underneath it: a scenario id and a weighting id
    // are the only inputs, so nothing a visitor types can reach a prompt. That
    // is what makes this the one example needing no moderation gate, and it
    // must not quietly acquire a text box.
    const { container } = renderScreen()
    await screen.findByTestId('agent-card-buyer')

    expect(container.querySelector('textarea')).toBeNull()
    expect(container.querySelector('input[type="text"]')).toBeNull()
    // The cards panel's own buttons are still just the three card toggles.
    const cards = screen.getByTestId('identity-cards')
    expect(within(cards).getAllByRole('button')).toHaveLength(CARDS.agents.length)
  })
})

describe('the collaboration entry in the shared app directory', () => {
  it('is registered as a live entry pointing at the collab route', () => {
    const entry = exampleApps.find((app) => app.id === 'multi_agent_collaboration_example_app')

    expect(entry).toBeDefined()
    expect(entry?.status).toBe('live')
    expect(entry?.route).toBe('/collab')
  })

  it('is last, as the highest pattern tier', () => {
    expect(exampleApps.at(-1)?.id).toBe('multi_agent_collaboration_example_app')
  })

  it('appears in both the landing catalogue and the persistent nav, from the one source', async () => {
    // The phase names catalogue/nav drift as a risk, with "verify by test that
    // the entry appears in both from that one declaration" as the mitigation.
    // `landing.test.tsx` mocks `example-apps`, so it checks the rendering logic
    // rather than the real catalogue — this uses the real one for both.
    const user = userEvent.setup()
    const entry = exampleApps.find((app) => app.id === 'multi_agent_collaboration_example_app')!

    const landing = createMemoryRouter([{ path: '/', element: <LandingScreen /> }])
    const { unmount } = render(<RouterProvider router={landing} />)
    expect(screen.getByText(entry.name)).toBeInTheDocument()
    unmount()

    render(
      <MemoryRouter>
        <NavMenu />
      </MemoryRouter>,
    )
    await user.click(screen.getByRole('button', { name: /menu/i }))
    expect(screen.getByText(entry.name)).toBeInTheDocument()
  })

  it('resolves to the real screen rather than the coming-soon placeholder', async () => {
    const router = createMemoryRouter(
      [{ path: '/collab', element: <CollabScreen /> }],
      { initialEntries: ['/collab'] },
    )
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    mockedFetch.mockResolvedValue(CARDS)

    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )

    expect(
      await screen.findByRole('heading', { name: /Multi-Agent Collaboration Example App/i }),
    ).toBeInTheDocument()
  })
})

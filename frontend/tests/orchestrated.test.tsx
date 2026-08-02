// Built with Spec4 AI - https://spec4.ai
/**
 * The orchestrated route's connectivity and its one standing content rule.
 *
 * Written for the Phase 1 integration thread and kept — narrowed to what is
 * still true — once the real screen replaced the placeholder: the route
 * resolves inside the shared layout, the roster comes from the API rather than
 * a frontend copy that could drift from the closed set the server validates
 * against, and the presets' expected pairings never reach the screen.
 *
 * The screen's behaviour lives in `orchestrated-screen.test.tsx`. What is here
 * is deliberately the part that has no reason to change again.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { exampleApps } from '../src/data/example-apps'
import type { RosterResponse } from '../src/api/orchestrated'
import { OrchestratedApp } from '../src/apps/orchestrated/OrchestratedApp'
import { OrchestratedScreen } from '../src/screens/orchestrated/OrchestratedScreen'

const ROSTER: RosterResponse = {
  specialists: [
    {
      id: 'technical',
      displayName: 'Technical Analyst',
      scope: 'Mechanism and trade-offs.',
      color: '#4ea1ff',
    },
    {
      id: 'financial',
      displayName: 'Financial Analyst',
      scope: 'Cost and quantitative framing.',
      color: '#f6b93b',
    },
    {
      id: 'historical',
      displayName: 'Historical Contextualiser',
      scope: 'Precedent and context.',
      color: '#7c5cff',
    },
    {
      id: 'practical',
      displayName: 'Practical Practitioner',
      scope: 'Concrete steps.',
      color: '#34d399',
    },
  ],
  presets: [
    {
      id: 'self-host-database',
      text: 'Should a small team self-host its own database?',
      expectedPairing: ['technical', 'financial'],
    },
    {
      id: 'apartment-composting',
      text: 'How should I start composting in a small apartment?',
      expectedPairing: ['practical', 'technical'],
    },
  ],
}

function stubRoster(body: unknown = ROSTER, ok = true) {
  const stub = vi.fn(async () => new Response(JSON.stringify(body), { status: ok ? 200 : 503 }))
  vi.stubGlobal('fetch', stub)
  return stub
}

function renderApp(element = <OrchestratedApp />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{element}</QueryClientProvider>)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the orchestrated route', () => {
  it('renders all four specialist display names from the roster', async () => {
    stubRoster()
    renderApp()

    const panel = await screen.findByTestId('specialist-roster')
    for (const specialist of ROSTER.specialists) {
      expect(within(panel).getByText(specialist.displayName)).toBeInTheDocument()
    }
    expect(within(panel).getAllByRole('listitem')).toHaveLength(4)
  })

  it('fetches the roster from the API rather than hardcoding it', async () => {
    // The roster is the closed set the coordinator's delegation is validated
    // against server-side. A frontend copy would drift and offer a specialist
    // the server would refuse.
    const stub = stubRoster()
    renderApp()

    await screen.findByTestId('specialist-roster')
    expect(stub).toHaveBeenCalledOnce()
    expect(stub.mock.calls[0][0]).toMatch(/\/api\/orchestrated\/roster$/)
  })

  it('offers every curated preset as a one-click chip', async () => {
    stubRoster()
    renderApp()

    await screen.findByTestId('specialist-roster')
    for (const preset of ROSTER.presets) {
      expect(screen.getByRole('button', { name: preset.text })).toBeInTheDocument()
    }
  })

  it('does not reveal each preset’s expected pairing', async () => {
    // A human label for offline evaluation. On screen it would announce the
    // coordinator's decision before the coordinator has made it — the one
    // thing this app exists to let the visitor watch. Asserted on the chips
    // themselves, since the roster panel legitimately names all four.
    stubRoster()
    const { container } = renderApp()

    await screen.findByTestId('specialist-roster')
    for (const preset of ROSTER.presets) {
      const chip = screen.getByRole('button', { name: preset.text })
      expect(chip.textContent).toBe(preset.text)
    }
    expect(container.textContent).not.toContain('expectedPairing')
  })

  it('explains a roster that could not be loaded instead of rendering nothing', async () => {
    stubRoster({ detail: 'nope' }, false)
    renderApp()

    expect(await screen.findByRole('alert')).toHaveTextContent(/roster could not be loaded/i)
  })

  it('renders at /orchestrated inside the shared layout', async () => {
    stubRoster()
    const routing = createMemoryRouter([{ path: '/orchestrated', element: <OrchestratedScreen /> }], {
      initialEntries: ['/orchestrated'],
    })
    renderApp(<RouterProvider router={routing} />)

    expect(
      await screen.findByRole('heading', {
        name: 'Orchestrated-Subagents Example App',
        level: 1,
      }),
    ).toBeInTheDocument()
    expect(await screen.findByTestId('specialist-roster')).toBeInTheDocument()
  })
})

describe('the catalogue entry', () => {
  const entry = exampleApps.find((app) => app.id === 'orchestrated_subagents_example_app')

  it('is listed exactly once, as live, routed to /orchestrated', () => {
    // Exactly once matters: a duplicate tile would open the same app twice on
    // the landing page and appear twice in the nav.
    const matches = exampleApps.filter(
      (app) => app.id === 'orchestrated_subagents_example_app',
    )

    expect(matches).toHaveLength(1)
    expect(entry?.status).toBe('live')
    expect(entry?.route).toBe('/orchestrated')
  })

  it('is appended after the machinery progression rather than slotted into it', () => {
    // The newest app goes on the end. The first four ascend by machinery
    // required; inserting there would break a reading order the landing page
    // depends on.
    //
    // This asserts *position relative to the progression*, not "is last" --
    // which was the previous form and which the next appended app necessarily
    // breaks. "Is last" belongs with whichever app currently is, and lives in
    // that app's own suite. This is the same correction v5 Phase 7 made when
    // the planning test claimed it.
    const ids = exampleApps.map((app) => app.id)
    const progression = [
      'embeddings_example_app',
      'single_call_example_app',
      'rag_example_app',
      'tool_use_integration',
    ]

    expect(ids.slice(0, 4)).toEqual(progression)
    expect(ids.indexOf('orchestrated_subagents_example_app')).toBeGreaterThan(3)
  })

  it('explains the pattern rather than only selling the demo', () => {
    // `patternSummary` is what PatternSummary renders into the screen intro,
    // and it has to be about the technique — a visitor evaluating Spec4 should
    // be able to tell what they are looking at before running anything.
    expect(entry?.patternSummary).toMatch(/at the same time/i)
    expect(entry?.patternSummary).toMatch(/neither needs the other/i)
    // And it must say the limits are this deployment's choice, not the
    // pattern's — the same rule every other entry's summary follows.
    expect(entry?.patternSummary).toMatch(/not a limit of the pattern/i)
  })
})

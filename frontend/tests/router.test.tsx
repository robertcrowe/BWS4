// Built with Spec4 AI - https://spec4.ai
/**
 * The /router route: the screen renders the six presets from the API, and the
 * catalogue entry appears exactly once on the landing page and in the menu.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NavMenu } from '../src/components/NavMenu'
import { exampleApps } from '../src/data/example-apps'
import { LandingScreen } from '../src/screens/landing/LandingScreen'
import { RouterScreen } from '../src/screens/router/RouterScreen'
import { ROUTER_PRESETS, routerFetch } from './routerFixtures'

function withProviders(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>
  )
}

// The hook and the fetcher share a module, so the response is mocked at
// `fetch` rather than by replacing the fetcher: the test then exercises the
// wire mapping too.
const fetchMock = vi.fn()

beforeEach(() => {
  fetchMock.mockReset()
  fetchMock.mockImplementation(routerFetch())
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the Router screen', () => {
  it('lists all six presets from the presets response', async () => {
    render(withProviders(<RouterScreen />))

    const list = await screen.findByRole('list', { name: 'Preset requests' })
    const items = within(list).getAllByRole('button')
    expect(items).toHaveLength(6)
    for (const preset of ROUTER_PRESETS.presets) {
      expect(within(list).getByText(preset.request, { exact: false })).toBeInTheDocument()
    }
  })

  it('marks a preset selected when chosen', async () => {
    const user = userEvent.setup()
    render(withProviders(<RouterScreen />))

    const button = await screen.findByRole('button', { name: /Formula 1/ })
    await user.click(button)

    expect(button).toHaveAttribute('aria-pressed', 'true')
  })

  it('does not reveal the expected route or reason before a run', async () => {
    render(withProviders(<RouterScreen />))
    await screen.findByRole('list', { name: 'Preset requests' })

    expect(screen.queryByText('Near-miss.')).not.toBeInTheDocument()
  })

  it('shows the error message when presets cannot be fetched', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    render(withProviders(<RouterScreen />))

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the backend')
  })
})

describe('the Router screen when descriptions are not ready', () => {
  it('shows the server detail rather than invented descriptions', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: "The Router's route descriptions are not ready." }), {
        status: 503,
      }),
    )
    render(withProviders(<RouterScreen />))

    expect(await screen.findByRole('alert')).toHaveTextContent('not ready')
    expect(screen.queryByTestId('route-descriptions-block')).not.toBeInTheDocument()
  })
})

describe('the Router catalogue entry', () => {
  it('exists exactly once, labelled Router, live at /router', () => {
    const entries = exampleApps.filter((app) => app.id === 'router_example_app')

    expect(entries).toHaveLength(1)
    expect(entries[0].name).toBe('Router')
    expect(entries[0].patternTag).toBe('Router')
    expect(entries[0].status).toBe('live')
    expect(entries[0].route).toBe('/router')
  })

  it('is appended last, per the newest-last catalogue rule', () => {
    expect(exampleApps.at(-1)?.id).toBe('router_example_app')
  })

  it('appears exactly once on the landing page, linking to /router', () => {
    render(withProviders(<LandingScreen />))

    const links = screen.getAllByRole('link', { name: /^Router\b/ })
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute('href', '/router')
  })

  it('appears exactly once in the navigation menu', async () => {
    const user = userEvent.setup()
    render(withProviders(<NavMenu />))

    await user.click(screen.getByRole('button', { name: /open navigation menu/i }))

    const links = screen.getAllByRole('menuitem', { name: /^Router$/ })
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute('href', '/router')
  })
})

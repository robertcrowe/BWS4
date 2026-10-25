// Built with Spec4 AI - https://spec4.ai
/**
 * The landing directory and the navigation menu list exactly the same apps,
 * in the same order, because both are driven by the one catalogue — including
 * the entry labelled 'Router'.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { NavMenu } from '../src/components/NavMenu'
import { exampleApps } from '../src/data/example-apps'
import { LandingScreen } from '../src/screens/landing/LandingScreen'

function landingEntries(): Array<{ name: string; href: string | null }> {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <LandingScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return exampleApps.map((app) => {
    const link = screen.getAllByRole('link').find((candidate) =>
      within(candidate).queryAllByText(app.name, { exact: true }).length > 0,
    )
    return { name: app.name, href: link?.getAttribute('href') ?? null }
  })
}

async function navEntries(): Promise<Array<{ name: string; href: string | null }>> {
  const user = userEvent.setup()
  render(
    <MemoryRouter>
      <NavMenu />
    </MemoryRouter>,
  )
  await user.click(screen.getByRole('button', { name: /open navigation menu/i }))
  return screen
    .getAllByRole('menuitem')
    .filter((item) => item.textContent !== 'Home')
    .map((item) => ({ name: item.textContent ?? '', href: item.getAttribute('href') }))
}

describe('the landing directory and the navigation', () => {
  it('list exactly the same apps, in the same order, with the same links', async () => {
    const landing = landingEntries()
    document.body.innerHTML = ''
    const nav = await navEntries()

    expect(nav).toEqual(landing)
    expect(nav.map((entry) => entry.name)).toEqual(exampleApps.map((app) => app.name))
  })

  it("include the entry labelled 'Router', linking to /router in both", async () => {
    const landing = landingEntries().find((entry) => entry.name === 'Router')
    document.body.innerHTML = ''
    const nav = (await navEntries()).find((entry) => entry.name === 'Router')

    expect(landing).toEqual({ name: 'Router', href: '/router' })
    expect(nav).toEqual(landing)
  })
})

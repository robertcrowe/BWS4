// Built with Spec4 AI - https://spec4.ai
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import type { ExampleApp } from '../src/data/example-apps'
import { LandingScreen } from '../src/screens/landing/LandingScreen'

const { mockApps } = vi.hoisted(() => ({
  mockApps: [
    {
      id: 'live_app',
      name: 'Live Example App',
      description: 'A fully working example app.',
      patternTag: 'Test Pattern',
      status: 'live',
      route: '/live-app',
    },
    {
      id: 'soon_app',
      name: 'Coming Soon App',
      description: 'Not built yet.',
      patternTag: 'Future Pattern',
      status: 'coming-soon',
      route: '/soon-app',
    },
  ] satisfies ExampleApp[],
}))

vi.mock('../src/data/example-apps', () => ({
  exampleApps: mockApps,
}))

function renderLanding(extraRoutes: { path: string; element: React.ReactNode }[] = []) {
  const router = createMemoryRouter([{ path: '/', element: <LandingScreen /> }, ...extraRoutes])
  return render(<RouterProvider router={router} />)
}

describe('LandingScreen', () => {
  it('explains that BWS4 was built with Spec4', () => {
    renderLanding()

    expect(screen.getAllByText(/spec4/i).length).toBeGreaterThan(0)
  })

  it('renders a directory item for every entry in the example app directory', () => {
    renderLanding()

    for (const app of mockApps) {
      expect(screen.getByText(app.name)).toBeInTheDocument()
    }
  })

  it('navigates to a live entry route when clicked, without throwing', async () => {
    const user = userEvent.setup()
    renderLanding([
      { path: '/live-app', element: <p>You made it to the live app.</p> },
    ])

    await user.click(screen.getByText('Live Example App'))

    expect(await screen.findByText('You made it to the live app.')).toBeInTheDocument()
  })

  it('does not navigate a coming-soon entry', async () => {
    const user = userEvent.setup()
    renderLanding()

    await user.click(screen.getByText('Coming Soon App'))

    expect(screen.getByText('Coming Soon App')).toBeInTheDocument()
  })
})

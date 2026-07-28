// Built with Spec4 AI - https://spec4.ai
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { NavMenu } from '../src/components/NavMenu'
import { exampleApps } from '../src/data/example-apps'

function renderNavMenu() {
  return render(
    <MemoryRouter>
      <NavMenu />
    </MemoryRouter>,
  )
}

function menuButton() {
  return screen.getByRole('button', { name: /navigation menu/i })
}

describe('NavMenu', () => {
  it('is closed until the hamburger is clicked', () => {
    renderNavMenu()

    expect(menuButton()).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('lists home and every example app from the shared directory', async () => {
    const user = userEvent.setup()
    renderNavMenu()

    await user.click(menuButton())

    expect(menuButton()).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('menuitem', { name: 'Home' })).toBeInTheDocument()
    for (const app of exampleApps) {
      expect(screen.getByRole('menuitem', { name: new RegExp(app.name) })).toBeInTheDocument()
    }
  })

  it('links live apps to their route and leaves coming-soon entries unlinked', async () => {
    const user = userEvent.setup()
    renderNavMenu()

    await user.click(menuButton())

    for (const app of exampleApps) {
      const item = screen.getByRole('menuitem', { name: new RegExp(app.name) })
      if (app.status === 'live') {
        expect(item).toHaveAttribute('href', app.route)
      } else {
        expect(item).toHaveAttribute('aria-disabled', 'true')
        expect(item).not.toHaveAttribute('href')
      }
    }
  })

  it('closes when Escape is pressed', async () => {
    const user = userEvent.setup()
    renderNavMenu()

    await user.click(menuButton())
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('closes when a click lands outside the menu', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <NavMenu />
        <button type="button">elsewhere</button>
      </MemoryRouter>,
    )

    await user.click(menuButton())
    await user.click(screen.getByRole('button', { name: 'elsewhere' }))

    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })
})

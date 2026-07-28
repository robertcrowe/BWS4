// Built with Spec4 AI - https://spec4.ai
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { NavBar } from '../src/components/NavBar'

function renderNavBar() {
  return render(
    <MemoryRouter>
      <NavBar />
    </MemoryRouter>,
  )
}

describe('NavBar', () => {
  it('offers spec4.ai as its own destination, safely opened in a new tab', () => {
    renderNavBar()

    const link = screen.getByRole('link', { name: /spec4\.ai/i })

    expect(link).toHaveAttribute('href', 'https://spec4.ai')
    expect(link).toHaveAttribute('target', '_blank')
    // Without noopener the opened page gets a handle on this one via window.opener.
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('does not link to spec4.ai twice over', () => {
    renderNavBar()

    const spec4Links = screen
      .getAllByRole('link')
      .filter((link) => link.getAttribute('href') === 'https://spec4.ai')

    expect(spec4Links).toHaveLength(1)
  })

  it('keeps the brand pointing at the BWS4 home route, not at spec4.ai', () => {
    renderNavBar()

    // The byline sits inside the brand link, so it forms part of the
    // accessible name -- matched loosely rather than as exactly "BWS4".
    expect(screen.getByRole('link', { name: /^BWS4/ })).toHaveAttribute('href', '/')
  })
})

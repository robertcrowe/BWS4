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

  it('links to the repository, safely opened in a new tab', () => {
    renderNavBar()

    const link = screen.getByRole('link', { name: /github/i })

    expect(link).toHaveAttribute('href', 'https://github.com/robertcrowe/BWS4')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('gives the repository badge an accessible name, since it is icon-only', () => {
    renderNavBar()

    // The mark is decorative, so the link would otherwise have no name at all
    // and read as a bare "link" to a screen reader.
    const link = screen.getByRole('link', { name: /github/i })

    expect(link.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
    expect(link).toHaveTextContent('')
  })

  it('renders the mark inline rather than fetching a badge image', () => {
    const { container } = renderNavBar()

    // A shields.io <img> would put a third-party request on every page load
    // and render as a broken image whenever that host is unreachable.
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('a[href*="github"] svg')).not.toBeNull()
  })

  it('places the repository badge before the spec4.ai link', () => {
    renderNavBar()

    const [first, second] = screen
      .getAllByRole('link')
      .filter((link) => /github\.com|spec4\.ai/.test(link.getAttribute('href') ?? ''))

    expect(first).toHaveAttribute('href', 'https://github.com/robertcrowe/BWS4')
    expect(second).toHaveAttribute('href', 'https://spec4.ai')
  })

  it('keeps the brand pointing at the BWS4 home route, not at spec4.ai', () => {
    renderNavBar()

    // The byline sits inside the brand link, so it forms part of the
    // accessible name -- matched loosely rather than as exactly "BWS4".
    expect(screen.getByRole('link', { name: /^BWS4/ })).toHaveAttribute('href', '/')
  })
})

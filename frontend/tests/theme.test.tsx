// Built with Spec4 AI - https://spec4.ai
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ThemeToggle } from '../src/components/ThemeToggle'
import { useIsDarkTheme } from '../src/useIsDarkTheme'
import { THEME_STORAGE_KEY } from '../src/useTheme'

/** Pin the OS preference so tests exercise the stored-value path deterministically. */
function mockSystemPrefersLight(prefersLight: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: query.includes('prefers-color-scheme: light') ? prefersLight : !prefersLight,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  )
}

describe('theme toggle', () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.classList.remove('dark')
    delete document.documentElement.dataset.theme
    mockSystemPrefersLight(false)
  })

  it('toggles the DOM theme class and persists the choice to localStorage', async () => {
    const user = userEvent.setup()
    render(<ThemeToggle />)

    // System preference is dark and nothing is stored, so the app starts dark.
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')

    await user.click(screen.getByRole('button', { name: /switch to light theme/i }))

    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')

    await user.click(screen.getByRole('button', { name: /switch to dark theme/i }))

    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
  })

  it('restores a stored preference on reload, ignoring the system preference', () => {
    window.localStorage.setItem(THEME_STORAGE_KEY, 'light')
    mockSystemPrefersLight(false)

    // A fresh render stands in for a page reload: the hook re-reads localStorage.
    render(<ThemeToggle />)

    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(screen.getByRole('button', { name: /switch to dark theme/i })).toBeInTheDocument()
  })

  it('falls back to the system preference when nothing is stored', () => {
    mockSystemPrefersLight(true)

    render(<ThemeToggle />)

    expect(document.documentElement.classList.contains('dark')).toBe(false)
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light')
  })
})

describe('useIsDarkTheme', () => {
  beforeEach(() => {
    document.documentElement.classList.remove('dark')
  })

  it('tracks the root class so canvas-drawn content recolours with the toggle', async () => {
    function Probe() {
      return <span data-testid="probe">{useIsDarkTheme() ? 'dark' : 'light'}</span>
    }

    document.documentElement.classList.add('dark')
    render(<Probe />)
    expect(screen.getByTestId('probe')).toHaveTextContent('dark')

    // Simulates what ThemeToggle -> applyTheme does to the root element. The
    // plot cannot use `useTheme()` for this: that hook holds its own state,
    // so a second caller would never hear about the NavBar's toggle.
    document.documentElement.classList.remove('dark')
    await waitFor(() => expect(screen.getByTestId('probe')).toHaveTextContent('light'))
  })
})

// Built with Spec4 AI - https://spec4.ai
import { useCallback, useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

/** localStorage key holding the visitor's chosen theme (per the stack's persistence entry). */
export const THEME_STORAGE_KEY = 'theme_preference'

function isTheme(value: string | null): value is Theme {
  return value === 'light' || value === 'dark'
}

/** Read the stored preference, falling back to the OS/browser setting when unset. */
export function resolveInitialTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    if (isTheme(stored)) {
      return stored
    }
  } catch {
    // localStorage can throw in private-browsing modes — fall through to the system preference.
  }
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

/** Apply a theme to the document root so Tailwind's `dark:` variants take effect. */
export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  document.documentElement.dataset.theme = theme
}

/**
 * Read/write the visitor's light-dark theme preference.
 *
 * The initial value comes from localStorage, falling back to the system
 * preference when nothing has been stored yet. Every change is applied to the
 * document root and persisted locally — there is no backend round trip.
 *
 * Returns:
 *     The current theme, a setter, and a convenience toggle.
 */
export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(resolveInitialTheme)

  useEffect(() => {
    applyTheme(theme)
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme)
    } catch {
      // A failed write only costs persistence across visits, not the current session.
    }
  }, [theme])

  const setTheme = useCallback((next: Theme) => setThemeState(next), [])
  const toggleTheme = useCallback(
    () => setThemeState((current) => (current === 'dark' ? 'light' : 'dark')),
    [],
  )

  return { theme, setTheme, toggleTheme }
}

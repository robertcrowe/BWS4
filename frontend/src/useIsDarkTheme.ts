// Built with Spec4 AI - https://spec4.ai
import { useEffect, useState } from 'react'

/**
 * Track whether the dark theme is currently applied to the document root.
 *
 * Tailwind components never need this — their `dark:` variants react to the
 * root class on their own. It exists for content drawn outside CSS's reach,
 * currently the plotly canvas in the embeddings app, which needs explicit
 * colour values and must recolour when the visitor flips the toggle.
 *
 * It observes the root element rather than calling `useTheme()`, deliberately.
 * `useTheme` holds its own `useState`, so a second caller would get an
 * independent copy that never hears about the NavBar toggle's changes.
 * Watching the class that `applyTheme` sets means this stays correct no
 * matter which component owns the preference.
 *
 * Returns:
 *     Whether the `dark` class is present on `<html>`, updated on change.
 */
export function useIsDarkTheme(): boolean {
  const [isDark, setIsDark] = useState(() =>
    typeof document === 'undefined'
      ? true
      : document.documentElement.classList.contains('dark'),
  )

  useEffect(() => {
    const root = document.documentElement
    const sync = () => setIsDark(root.classList.contains('dark'))

    sync()
    const observer = new MutationObserver(sync)
    observer.observe(root, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])

  return isDark
}

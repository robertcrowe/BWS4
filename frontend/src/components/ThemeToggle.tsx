// Built with Spec4 AI - https://spec4.ai
import { useTheme } from '../useTheme'

/**
 * Header control that flips the app between light and dark mode. Rendered in
 * the shared NavBar, so it reaches the landing, RAG, and tool-use screens
 * identically; the choice persists in localStorage.
 */
export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  const isDark = theme === 'dark'

  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={`Switch to ${isDark ? 'light' : 'dark'} theme`}
      title={`Switch to ${isDark ? 'light' : 'dark'} theme`}
      className="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-2.5 py-1.5 text-sm leading-none hover:border-violet-500"
    >
      <span aria-hidden="true">{isDark ? '🌙' : '☀️'}</span>
    </button>
  )
}

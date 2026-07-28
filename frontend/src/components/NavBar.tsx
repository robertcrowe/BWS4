// Built with Spec4 AI - https://spec4.ai
import { Link } from 'react-router'

import { ThemeToggle } from './ThemeToggle'

/**
 * Sticky top navigation shared by the landing screen and every example-app
 * screen, keeping the brand and primary way home consistent across BWS4.
 */
export function NavBar() {
  return (
    <header className="sticky top-0 z-10 border-b border-gray-200 dark:border-gray-800 bg-white/80 dark:bg-gray-950/85 px-6 py-3.5 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-2">
        <Link to="/" className="flex items-center gap-2">
          <span className="bg-gradient-to-r from-violet-600 dark:from-violet-400 to-blue-600 dark:to-blue-400 bg-clip-text text-lg font-extrabold tracking-tight text-transparent">
            BWS4
          </span>
          <span className="font-mono text-xs text-gray-500">/ Built with Spec4</span>
        </Link>
        <div className="flex items-center gap-3">
          <Link
            to="/console"
            className="font-mono text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
          >
            Framework Console
          </Link>
          <ThemeToggle />
        </div>
      </div>
    </header>
  )
}

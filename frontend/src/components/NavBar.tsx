// Built with Spec4 AI - https://spec4.ai
import { Link } from 'react-router'

import { NavMenu } from './NavMenu'
import { ThemeToggle } from './ThemeToggle'

/**
 * Sticky top navigation shared by the landing screen and every example-app
 * screen, keeping the brand and primary way home consistent across BWS4.
 */
export function NavBar() {
  return (
    <header className="sticky top-0 z-10 border-b border-gray-200 dark:border-gray-800 bg-white/80 dark:bg-gray-950/85 px-6 py-3.5 backdrop-blur">
      <div className="mx-auto flex max-w-5xl items-center justify-between gap-2">
        {/* The byline stays plain text: spec4.ai is reachable as its own
            destination on the right, and two links to one URL in a single
            header is noise. */}
        <Link to="/" className="flex items-center gap-2">
          <span className="bg-gradient-to-r from-violet-600 dark:from-violet-400 to-blue-600 dark:to-blue-400 bg-clip-text text-lg font-extrabold tracking-tight text-transparent">
            BWS4
          </span>
          <span className="font-mono text-xs text-gray-500">/ Built with Spec4</span>
        </Link>
        <div className="flex items-center gap-2">
          <a
            href="https://spec4.ai"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-lg border border-violet-500/40 bg-violet-500/5 px-3 py-1.5 text-sm font-semibold text-violet-600 hover:border-violet-500 hover:bg-violet-500/10 dark:text-violet-400"
          >
            spec4.ai <span aria-hidden="true">↗</span>
          </a>
          <ThemeToggle />
          <NavMenu />
        </div>
      </div>
    </header>
  )
}

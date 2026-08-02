// Built with Spec4 AI - https://spec4.ai
import { Link } from 'react-router'

import { NavMenu } from './NavMenu'
import { ThemeToggle } from './ThemeToggle'

/** The public repository this showcase is built in. Deliberately not exported:
 *  a test importing it would assert the constant against itself. */
const REPO_URL = 'https://github.com/robertcrowe/BWS4'

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
          {/* Inline mark rather than a shields.io image: the badge would
              otherwise be a third-party request on every page load, and one
              that renders as a broken image if that host is unreachable. */}
          <a
            href={REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="View the BWS4 source on GitHub"
            title="View the BWS4 source on GitHub"
            className="rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-2.5 py-1.5 leading-none text-gray-700 hover:border-violet-500 dark:text-gray-300"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4 fill-current" aria-hidden="true">
              <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
            </svg>
          </a>
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

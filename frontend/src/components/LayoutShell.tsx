// Built with Spec4 AI - https://spec4.ai
import type { ReactNode } from 'react'

import { NavBar } from './NavBar'

interface LayoutShellProps {
  children: ReactNode
}

/**
 * Shared page frame (nav bar, content well, footer) so the landing screen
 * and every future example-app screen present a consistent structure.
 */
export function LayoutShell({ children }: LayoutShellProps) {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100">
      <NavBar />
      <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
      <footer className="border-t border-gray-200 dark:border-gray-800 py-5 text-center font-mono text-xs text-gray-500">
        BWS4 — every screen, pattern demo, and shared service above was built with Spec4.
      </footer>
    </div>
  )
}

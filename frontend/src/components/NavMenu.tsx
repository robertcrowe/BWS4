// Built with Spec4 AI - https://spec4.ai
import { useEffect, useId, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router'

import { exampleApps } from '../data/example-apps'

/**
 * Hamburger navigation in the header, listing every route a visitor can reach.
 *
 * Entries come from example-apps.ts so the menu can't fall out of step with
 * the landing directory: 'coming-soon' apps are listed but not linked, exactly
 * as their directory cards behave. Every route reachable from here is public --
 * there is deliberately no operator-only surface. Closes on outside click, on
 * Escape, and on navigation.
 */
export function NavMenu() {
  const [isOpen, setIsOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const menuId = useId()
  const { pathname } = useLocation()

  // Navigating away must not leave the panel hanging open over the new screen.
  useEffect(() => {
    setIsOpen(false)
  }, [pathname])

  useEffect(() => {
    if (!isOpen) {
      return
    }

    function handlePointerDown(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsOpen(false)
      }
    }

    document.addEventListener('mousedown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
        aria-controls={menuId}
        aria-haspopup="menu"
        aria-label={isOpen ? 'Close navigation menu' : 'Open navigation menu'}
        className="flex items-center justify-center rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-2.5 py-2 hover:border-violet-500"
      >
        <span className="flex h-3.5 w-4 flex-col justify-between" aria-hidden="true">
          <span className="h-0.5 w-full rounded-full bg-gray-600 dark:bg-gray-300" />
          <span className="h-0.5 w-full rounded-full bg-gray-600 dark:bg-gray-300" />
          <span className="h-0.5 w-full rounded-full bg-gray-600 dark:bg-gray-300" />
        </span>
      </button>

      {isOpen && (
        <div
          id={menuId}
          role="menu"
          className="absolute right-0 top-full z-20 mt-2 w-64 overflow-hidden rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 py-1.5 shadow-lg"
        >
          <MenuLink to="/" label="Home" />

          <MenuHeading>Example apps</MenuHeading>
          {exampleApps.map((app) =>
            app.status === 'live' ? (
              <MenuLink key={app.id} to={app.route} label={app.name} />
            ) : (
              <MenuDisabled key={app.id} label={app.name} />
            ),
          )}
        </div>
      )}
    </div>
  )
}

function MenuHeading({ children }: { children: string }) {
  return (
    <p className="px-3.5 pb-1 pt-2.5 font-mono text-[11px] uppercase tracking-wide text-gray-400 dark:text-gray-500">
      {children}
    </p>
  )
}

function MenuLink({ to, label }: { to: string; label: string }) {
  return (
    <Link
      to={to}
      role="menuitem"
      className="block px-3.5 py-2 text-sm text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
    >
      {label}
    </Link>
  )
}

function MenuDisabled({ label }: { label: string }) {
  return (
    <span
      role="menuitem"
      aria-disabled="true"
      className="block cursor-not-allowed px-3.5 py-2 text-sm text-gray-400 dark:text-gray-600"
    >
      {label} <span className="font-mono text-[11px]">· soon</span>
    </span>
  )
}

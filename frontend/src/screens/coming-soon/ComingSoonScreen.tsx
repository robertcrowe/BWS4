// Built with Spec4 AI - https://spec4.ai
import { Link } from 'react-router'

import { LayoutShell } from '../../components/LayoutShell'

interface ComingSoonScreenProps {
  name: string
  description: string
}

/**
 * Placeholder rendered for an example app's route before its screen and
 * backend support are implemented, so the route resolves instead of
 * leaving visitors at a broken link.
 */
export function ComingSoonScreen({ name, description }: ComingSoonScreenProps) {
  return (
    <LayoutShell>
      <div className="mx-auto max-w-xl py-16 text-center">
        <span className="inline-block rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs uppercase tracking-wide text-gray-600 dark:text-gray-400">
          Coming soon
        </span>
        <h1 className="mt-4 text-2xl font-semibold text-gray-900 dark:text-gray-100">{name}</h1>
        <p className="mt-3 text-gray-600 dark:text-gray-400">{description}</p>
        <Link to="/" className="mt-8 inline-block text-sm font-semibold text-blue-600 dark:text-blue-400">
          ← Back to the example app directory
        </Link>
      </div>
    </LayoutShell>
  )
}

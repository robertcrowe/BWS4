// Built with Spec4 AI - https://spec4.ai
import { ConsoleApp } from './ConsoleApp'
import { LayoutShell } from '../../components/LayoutShell'

/**
 * screen-console: the framework_services_console's route-level screen, a
 * maintainer-facing surface distinct from the visitor-facing example apps.
 */
export function ConsoleScreen() {
  return (
    <LayoutShell>
      <div className="py-2">
        <div className="mb-4 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-400" />
            Audience: Spec4 team / maintainers
          </span>
          <span className="rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs text-gray-600 dark:text-gray-400">
            Shared Framework Services
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">Framework Services Console</h1>
        <p className="mt-2 max-w-2xl text-sm text-gray-600 dark:text-gray-400">
          Every example app calls the same three shared capabilities — text generation, text
          representation, and data storage/retrieval — through one consistent interface. Test that
          interface directly, watch usage limits move, and see requests logged across apps.
        </p>
      </div>

      <div className="mt-6">
        <ConsoleApp />
      </div>
    </LayoutShell>
  )
}

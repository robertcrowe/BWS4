// Built with Spec4 AI - https://spec4.ai
import type { Specialist } from '../../api/orchestrated'

/**
 * The fixed roster, with the chosen pair marked once a decision exists.
 *
 * Showing all four is what makes the coordinator's job legible: the visitor can
 * see the closed set it had to pick exactly two from, so the choice reads as a
 * decision rather than as whatever the app happened to do. The colours come
 * from the roster config's own `color` field, so a column's accent and its
 * roster entry can never disagree.
 */
export interface SpecialistRosterProps {
  specialists: Specialist[]
  /** Ids the coordinator picked, once it has. */
  chosen?: string[]
}

/**
 * Render the four-specialist roster.
 *
 * @param props - The roster and the currently chosen ids.
 * @returns The roster panel.
 */
export function SpecialistRoster({ specialists, chosen = [] }: SpecialistRosterProps) {
  return (
    <section className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900">
      <h3 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">
        Specialist roster (fixed — exactly two are chosen per run)
      </h3>
      <ul className="grid gap-3 sm:grid-cols-2" data-testid="specialist-roster">
        {specialists.map((specialist) => {
          const isChosen = chosen.includes(specialist.id)
          return (
            <li
              key={specialist.id}
              data-testid={`roster-${specialist.id}`}
              data-chosen={isChosen ? 'true' : 'false'}
              className={
                'rounded-xl border p-3 transition-colors ' +
                (isChosen
                  ? 'border-violet-400 bg-violet-50 dark:border-violet-500/60 dark:bg-violet-950/30'
                  : 'border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-gray-950')
              }
            >
              <p className="flex items-center gap-2 text-sm font-medium text-gray-900 dark:text-gray-100">
                <span
                  aria-hidden="true"
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{ backgroundColor: specialist.color }}
                />
                {specialist.displayName}
                {isChosen ? (
                  <span className="rounded-full bg-violet-600 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-white uppercase">
                    chosen
                  </span>
                ) : null}
              </p>
              <p className="mt-1.5 text-xs leading-relaxed text-gray-600 dark:text-gray-400">
                {specialist.scope}
              </p>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

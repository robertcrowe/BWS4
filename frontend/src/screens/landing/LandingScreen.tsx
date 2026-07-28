// Built with Spec4 AI - https://spec4.ai
import { Link } from 'react-router'

import { LayoutShell } from '../../components/LayoutShell'
import type { ExampleApp } from '../../data/example-apps'
import { exampleApps } from '../../data/example-apps'

/**
 * Entry point to BWS4: explains that the app and its examples were built
 * with Spec4, and lists every example app currently available to explore.
 */
export function LandingScreen() {
  return (
    <LayoutShell>
      <section className="py-8 text-center">
        <span className="inline-flex items-center gap-2 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 px-3 py-1 font-mono text-xs uppercase tracking-wide text-gray-600 dark:text-gray-400">
          Teaching framework · dogfooded on itself
        </span>
        <h1 className="mt-5 bg-gradient-to-r from-violet-600 dark:from-violet-400 to-blue-600 dark:to-blue-400 bg-clip-text text-4xl font-bold tracking-tight text-transparent">
          Built with Spec4 (BWS4)
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-gray-600 dark:text-gray-400">
          BWS4 is a framework and a growing collection of example apps that demonstrate what
          Spec4 can build. Every example below — including this landing page — was built using
          Spec4, so you&apos;re looking at a live demonstration, not a slide deck.
        </p>
      </section>

      <section className="mt-8">
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Example App Directory</h2>
          <span className="font-mono text-xs text-gray-500">
            derived from the current set of available example apps
          </span>
        </div>

        {exampleApps.length === 0 ? (
          <p className="py-10 text-center text-sm text-gray-500">
            No example apps are available yet — check back soon.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {exampleApps.map((app) => (
              <ExampleAppCard key={app.id} app={app} />
            ))}
          </div>
        )}
      </section>
    </LayoutShell>
  )
}

function ExampleAppCard({ app }: { app: ExampleApp }) {
  const isLive = app.status === 'live'
  const cardClassName = [
    'block rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5 text-left transition',
    isLive ? 'cursor-pointer hover:-translate-y-0.5 hover:border-violet-500' : 'opacity-60',
  ].join(' ')

  const cardBody = (
    <>
      <span className="inline-flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wide text-gray-600 dark:text-gray-400">
        <span className="h-1.5 w-1.5 rounded-full bg-blue-400" />
        {app.patternTag}
      </span>
      <h3 className="mt-2 text-base font-semibold text-gray-900 dark:text-gray-100">{app.name}</h3>
      <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">{app.description}</p>
      <div className="mt-4 text-sm font-semibold text-blue-600 dark:text-blue-400">
        {isLive ? 'Open example →' : 'Coming soon'}
      </div>
    </>
  )

  if (isLive) {
    return (
      <Link to={app.route} className={cardClassName}>
        {cardBody}
      </Link>
    )
  }

  return (
    <div className={cardClassName} aria-disabled="true">
      {cardBody}
    </div>
  )
}

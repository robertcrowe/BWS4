// Built with Spec4 AI - https://spec4.ai
import { describe, expect, it } from 'vitest'

import { exampleApps } from '../src/data/example-apps'
import { router } from '../src/routes'

/**
 * The landing page's directory and the router are two views of one list, and
 * nothing checked they agreed.
 *
 * `landing_page`'s success criteria require that every available example app
 * "can be opened from" the listing, and its failure modes name the exact break:
 * an entry that links to an app that fails to open. Both were confirmed by hand
 * each phase, which verifies the moment rather than the invariant — the next app
 * added is the one that gets it wrong.
 *
 * Reads the real router and the real directory. Mocking either would make this
 * a test of the mock.
 */
const declaredPaths = new Set(
  router.routes.map((route) => route.path).filter((path): path is string => Boolean(path)),
)

/** Paths routes.tsx derives from 'coming-soon' entries and points at the placeholder. */
const comingSoonPaths = new Set(
  exampleApps.filter((app) => app.status === 'coming-soon').map((app) => app.route),
)

describe('the app directory and the router', () => {
  it('declares a route for every entry in the directory', () => {
    // Covers both statuses: a coming-soon entry still needs its route to
    // resolve, or its card links into a blank screen.
    for (const app of exampleApps) {
      expect(declaredPaths, `${app.name} (${app.route}) has no route`).toContain(app.route)
    }
  })

  it('does not route a live entry to the coming-soon placeholder', () => {
    // The specific trap: flipping an entry's status to 'live' without adding
    // its real lazy route leaves the card clickable and the screen a stub.
    for (const app of exampleApps.filter((entry) => entry.status === 'live')) {
      expect(comingSoonPaths, `${app.name} is live but still placeholder-routed`).not.toContain(
        app.route,
      )
    }
  })

  it('has a catalogue entry for every example-app route, and vice versa', () => {
    // The feature's first-named failure runs in **both** directions: a
    // catalogue that lists an app which cannot be opened, and a route that
    // exists with no way to reach it. Set equality catches duplication and
    // divergence in one assertion, so the next app added cannot register in
    // only one of the two places.
    //
    // The exclusions are the routes that are not example apps. Listing them
    // explicitly means a new infrastructure route is a deliberate line here
    // rather than something that quietly slips past the check.
    const NON_APP_PATHS = new Set(['/', '/health'])

    const appRoutes = new Set([...declaredPaths].filter((path) => !NON_APP_PATHS.has(path)))
    const catalogueRoutes = new Set(exampleApps.map((app) => app.route))

    expect([...appRoutes].sort()).toEqual([...catalogueRoutes].sort())
  })

  it('gives every entry a distinct route', () => {
    const routes = exampleApps.map((app) => app.route)

    // Two entries sharing a path means one of them is unreachable, and which
    // one wins depends on router ordering rather than on anything intentional.
    expect(new Set(routes).size).toBe(routes.length)
  })

  it('lists the Single Call app as live and routable', () => {
    // Phase 4's own instruction 1, as an assertion rather than a manual look.
    const entry = exampleApps.find((app) => app.id === 'single_call_example_app')

    expect(entry?.status).toBe('live')
    expect(declaredPaths).toContain('/single-call')
    expect(comingSoonPaths).not.toContain('/single-call')
  })

  it('has every live example app the phase set claims to have shipped', () => {
    const live = exampleApps.filter((app) => app.status === 'live').map((app) => app.id)

    expect(live).toEqual(
      expect.arrayContaining([
        'rag_example_app',
        'tool_use_integration',
        'single_call_example_app',
        'embeddings_example_app',
        'chained_calls_example_app',
        'planning_agent_example_app',
        'orchestrated_subagents_example_app',
      ]),
    )
  })
})

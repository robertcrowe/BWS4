// Built with Spec4 AI - https://spec4.ai
import { initAnalytics, trackPageView } from '../analytics'
import { applyMeta } from './applyMeta'
import { metaForPath } from './siteMeta'

/**
 * Keep the document head and the analytics page-view count in step with the route.
 *
 * ## Why this subscribes to the router instead of being a hook
 *
 * The obvious React shape is a `useLocation` hook in a layout component — but
 * this router has no layout route. `routes.tsx` is a **flat** array of eleven
 * paths, and `routes.test.tsx` reads `router.routes.map(route => route.path)`
 * to pin the catalogue and the router against each other in both directions.
 * Introducing a pathless parent to hang a hook on would nest every route one
 * level deeper and break that check — trading a real invariant for a
 * stylistic preference.
 *
 * `router.subscribe` is a supported API on the data router and needs no change
 * to the route tree at all. What it costs is that this runs outside React,
 * which is why the two things it does are pure functions defined elsewhere:
 * `metaForPath` decides, `applyMeta` writes.
 *
 * ## Why it fires only when navigation settles
 *
 * Subscribers are called for every router state change, including the moment a
 * navigation *starts* — at which point `state.location` is already the new one
 * while the lazy chunk is still loading. Acting then would record a page view
 * for a screen the visitor may never see if the navigation is superseded, and
 * would set the title before the page it names exists. Waiting for
 * `navigation.state === 'idle'` and for the location key to actually change
 * makes it one update per completed navigation.
 */

/** Minimal shape of the router state this needs, so tests need no real router. */
export interface SeoRouterState {
  location: { pathname: string; key?: string }
  navigation: { state: string }
}

/** Just enough of the data router to subscribe to, for the same reason. */
export interface SeoRouter {
  state: SeoRouterState
  subscribe: (fn: (state: SeoRouterState) => void) => () => void
}

/**
 * Apply the current route's metadata and count it as a page view.
 *
 * @param pathname - The route to describe.
 */
function update(pathname: string): void {
  const meta = metaForPath(pathname)
  applyMeta(meta)
  trackPageView(pathname, meta.title)
}

/**
 * Start tracking. Applies the landing route immediately, then every navigation.
 *
 * @param router - The application router.
 * @returns The unsubscribe function, so a test can tear it down.
 */
export function installSeo(router: SeoRouter): () => void {
  initAnalytics()

  // The first page view is sent here rather than by `gtag('config')`, so the
  // load and every navigation after it go through one code path.
  let lastKey = router.state.location.key ?? router.state.location.pathname
  update(router.state.location.pathname)

  return router.subscribe((state) => {
    if (state.navigation.state !== 'idle') {
      return
    }
    const key = state.location.key ?? state.location.pathname
    if (key === lastKey) {
      return
    }
    lastKey = key
    update(state.location.pathname)
  })
}

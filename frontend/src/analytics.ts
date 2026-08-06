// Built with Spec4 AI - https://spec4.ai

/**
 * Google Analytics 4, loaded from here rather than hardcoded into `index.html`.
 *
 * ## Why not a script tag in the HTML
 *
 * spec4.ai puts the gtag snippet straight in its `<head>`, which is right for a
 * static site with no dev server. BWS4 has `npm run dev` and 28 Vitest files,
 * and a snippet in `index.html` cannot be conditioned on the environment — so
 * every local dev session would be counted as a visitor. On a showcase whose
 * whole purpose is measuring visitor interest, conflating the developer's own
 * traffic with real traffic makes the numbers worse than not having them.
 *
 * So loading is gated on `import.meta.env.PROD`. `npm run dev` and the test
 * suite send nothing, and there is no way to accidentally turn that on.
 *
 * ## Why page views are sent by hand
 *
 * `gtag('config', ID)` sends exactly one `page_view`, on load. This is a
 * single-page app: a visitor who opens the landing page and then four example
 * apps performs one page load and five navigations, and GA would record the
 * first. `send_page_view: false` turns the automatic one off and
 * `trackPageView` sends every navigation including the first, so the count is
 * of pages seen rather than of tabs opened.
 *
 * ## The measurement ID is not a secret
 *
 * It is visible in the page source of every GA-instrumented site on the web.
 * It is still overridable through `VITE_GA_MEASUREMENT_ID` so a fork points at
 * its own property — or, set to an empty string, at none at all. That mirrors
 * how `VITE_SENTRY_DSN` works here: third-party reporting is configurable and
 * no-ops cleanly when it is switched off.
 */

/** The property BWS4 reports to. Overridable; empty disables analytics entirely. */
export const GA_MEASUREMENT_ID: string =
  import.meta.env.VITE_GA_MEASUREMENT_ID ?? 'G-PS571XRB2G'

declare global {
  interface Window {
    dataLayer?: unknown[]
    gtag?: (...args: unknown[]) => void
  }
}

/**
 * Whether analytics should run at all.
 *
 * Both conditions are load-bearing: the build gate keeps developer traffic out
 * of the property, and the id gate is what makes a fork able to switch it off.
 *
 * @returns True when a production build has a measurement id configured.
 */
export function analyticsEnabled(): boolean {
  return import.meta.env.PROD && GA_MEASUREMENT_ID !== ''
}

/**
 * Load gtag.js and configure the property, once.
 *
 * Safe to call more than once — a second call is a no-op rather than a second
 * script tag. Does nothing at all when `analyticsEnabled()` is false, so no
 * request leaves the browser in dev or under test.
 */
export function initAnalytics(): void {
  if (!analyticsEnabled() || window.gtag) {
    return
  }

  const script = document.createElement('script')
  script.async = true
  script.src = `https://www.googletagmanager.com/gtag/js?id=${GA_MEASUREMENT_ID}`
  document.head.appendChild(script)

  window.dataLayer = window.dataLayer || []
  // gtag's documented shape: it forwards its `arguments` object, not an array.
  function gtag(...args: unknown[]): void {
    window.dataLayer?.push(args)
  }
  window.gtag = gtag

  gtag('js', new Date())
  gtag('config', GA_MEASUREMENT_ID, {
    // Every page view is sent explicitly by `trackPageView`, including the
    // first — see the module docstring.
    send_page_view: false,
  })
}

/**
 * Record one page view.
 *
 * @param path - The route's pathname, which becomes `page_path` in GA.
 * @param title - The document title for that route.
 */
export function trackPageView(path: string, title: string): void {
  if (!analyticsEnabled()) {
    return
  }
  window.gtag?.('event', 'page_view', {
    page_path: path,
    page_title: title,
    page_location: `${window.location.origin}${path}`,
  })
}

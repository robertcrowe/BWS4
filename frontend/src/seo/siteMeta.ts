// Built with Spec4 AI - https://spec4.ai
import { exampleApps } from '../data/example-apps'

/**
 * Per-route page metadata, derived from the one catalogue everything else reads.
 *
 * **A single-page app serves one `index.html` to every URL**, so without this
 * all eleven routes would present the identical title, description and
 * canonical link — and a search engine would see eleven copies of one page.
 * That is the single largest SEO problem this architecture creates, and it is
 * not fixed by the static tags in `index.html`; those only establish the
 * defaults a crawler sees before any script runs.
 *
 * Driven by `example-apps.ts` rather than by a second list, for the same reason
 * `routes.tsx`, `NavMenu` and `PatternSummary` are: a tenth example app should
 * arrive with its title, description and sitemap entry already correct, not
 * with three more places to remember. `frontend/tests/seo.test.ts` pins the
 * agreement in both directions, exactly as `routes.test.tsx` pins the router's.
 *
 * Pure and DOM-free on purpose — the repo's established way of keeping display
 * logic testable without rendering. `applyMeta.ts` does the writing.
 */

/** The deployed origin. Canonical URLs are absolute, which is what makes them useful. */
export const SITE_ORIGIN = 'https://bw.spec4.ai'

/** The `og:site_name` every page shares. */
export const SITE_NAME = 'Built with Spec4'

/** The landing page's title, and the suffix every other page carries. */
export const DEFAULT_TITLE = 'Built with Spec4 — a working gallery of AI application patterns'

/**
 * The site-level description.
 *
 * Written to be true rather than to rank: it names the patterns, because those
 * are the words someone looking for a worked example of "ReAct loop" or
 * "orchestrated subagents" would actually type.
 */
export const DEFAULT_DESCRIPTION =
  'Nine small example apps, each demonstrating one AI application pattern end to end and ' +
  'every one built with Spec4: embeddings, single-call, RAG, tool use, chained calls, a ' +
  'planning agent, orchestrated subagents, multi-agent collaboration, and the ReAct loop. ' +
  'Open any of them and watch the pattern actually run.'

/** What a page's `<head>` should say. */
export interface PageMeta {
  title: string
  description: string
  /** Absolute, per the canonical-link contract. */
  canonical: string
}

/** Titles for the routes that are not example apps. */
const NON_APP_TITLES: Record<string, string> = {
  '/health': 'Service health — Built with Spec4',
}

const NON_APP_DESCRIPTIONS: Record<string, string> = {
  '/health':
    'Live connectivity check for the BWS4 API and its database, used to confirm the ' +
    'showcase backend is reachable.',
}

/**
 * Normalise a pathname so `/react`, `/react/` and `/React` resolve alike.
 *
 * A trailing slash and a bare path are the same page to a visitor and two URLs
 * to a crawler, which is the duplication a canonical link exists to collapse —
 * so both must produce the *same* canonical rather than each pointing at
 * itself.
 *
 * @param pathname - The location's pathname.
 * @returns The catalogue-shaped path, without a trailing slash.
 */
export function normalisePath(pathname: string): string {
  const trimmed = pathname.replace(/\/+$/, '').toLowerCase()
  return trimmed === '' ? '/' : trimmed
}

/**
 * Work out the title, description and canonical URL for one route.
 *
 * An unknown path falls back to the site defaults rather than inventing a
 * title from the URL — a 404 that describes itself as a real page is worse
 * than one that describes the site.
 *
 * @param pathname - The location's pathname.
 * @returns The metadata that route should present.
 */
export function metaForPath(pathname: string): PageMeta {
  const path = normalisePath(pathname)
  const canonical = `${SITE_ORIGIN}${path === '/' ? '/' : path}`

  const app = exampleApps.find((entry) => entry.route === path)
  if (app) {
    return {
      // The app's own name leads, because that is the phrase someone searched
      // for; the site name trails so a tab strip stays readable.
      title: `${app.name} — ${SITE_NAME}`,
      description: app.description,
      canonical,
    }
  }

  if (path in NON_APP_TITLES) {
    return {
      title: NON_APP_TITLES[path],
      description: NON_APP_DESCRIPTIONS[path],
      canonical,
    }
  }

  return {
    title: DEFAULT_TITLE,
    description: DEFAULT_DESCRIPTION,
    canonical: `${SITE_ORIGIN}/`,
  }
}

/**
 * Every URL that belongs in the sitemap, in display order.
 *
 * `/health` is deliberately absent: it is an operational probe, not a page
 * anyone should arrive at from a search result.
 *
 * @returns Absolute URLs — the landing page, then every live example app.
 */
export function sitemapUrls(): string[] {
  return [
    `${SITE_ORIGIN}/`,
    ...exampleApps
      .filter((app) => app.status === 'live')
      .map((app) => `${SITE_ORIGIN}${app.route}`),
  ]
}

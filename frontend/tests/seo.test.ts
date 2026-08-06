// Built with Spec4 AI - https://spec4.ai
/**
 * The head tags, the sitemap, and the analytics that must not fire in dev.
 *
 * Three properties carry this file:
 *
 * 1. **Every route says something different.** A single-page app serves one
 *    `index.html` to all eleven paths, so the failure this guards is eleven
 *    URLs presenting one title, one description and one canonical link — which
 *    is a crawler's definition of duplicate content. Asserted per route rather
 *    than in general.
 * 2. **The sitemap and the catalogue agree.** Same shape, and the same reason,
 *    as `routes.test.tsx` pinning the catalogue against the router: the tenth
 *    example app must not ship listed in one place and missing from the other.
 * 3. **Analytics is off outside a production build.** Vitest runs with
 *    `PROD === false`, so this is asserted rather than assumed — a snippet that
 *    counted developer traffic would be invisible until the numbers were
 *    already wrong.
 *
 * `index.html` is read from disk, not from a rendered document: it is the file
 * a crawler that runs no JavaScript actually receives, and nothing else in the
 * suite would notice if a tag were dropped from it.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { beforeEach, describe, expect, it } from 'vitest'

import { analyticsEnabled, GA_MEASUREMENT_ID, initAnalytics, trackPageView } from '../src/analytics'
import { exampleApps } from '../src/data/example-apps'
import { applyMeta } from '../src/seo/applyMeta'
import type { SeoRouterState } from '../src/seo/installSeo'
import { installSeo } from '../src/seo/installSeo'
import {
  DEFAULT_DESCRIPTION,
  DEFAULT_TITLE,
  SITE_ORIGIN,
  metaForPath,
  normalisePath,
  sitemapUrls,
} from '../src/seo/siteMeta'

const FRONTEND = resolve(__dirname, '..')
const INDEX_HTML = readFileSync(resolve(FRONTEND, 'index.html'), 'utf8')
const SITEMAP = readFileSync(resolve(FRONTEND, 'public/sitemap.xml'), 'utf8')
const ROBOTS = readFileSync(resolve(FRONTEND, 'public/robots.txt'), 'utf8')

const LIVE_APPS = exampleApps.filter((app) => app.status === 'live')

describe('the static head every crawler sees first', () => {
  it('carries a title, a description and a canonical link', () => {
    expect(INDEX_HTML).toContain(`<title>${DEFAULT_TITLE}</title>`)
    expect(INDEX_HTML).toContain('<meta\n      name="description"')
    expect(INDEX_HTML).toContain(`<link rel="canonical" href="${SITE_ORIGIN}/" />`)
  })

  it('carries the Open Graph set a link preview needs', () => {
    for (const property of [
      'og:type',
      'og:url',
      'og:site_name',
      'og:title',
      'og:description',
      'og:image',
      'og:image:width',
      'og:image:height',
      'og:image:alt',
    ]) {
      expect(INDEX_HTML, `${property} is missing`).toContain(`property="${property}"`)
    }
  })

  it('carries the Twitter card set', () => {
    for (const name of ['twitter:card', 'twitter:title', 'twitter:description', 'twitter:image']) {
      expect(INDEX_HTML, `${name} is missing`).toContain(`name="${name}"`)
    }
    expect(INDEX_HTML).toContain('content="summary_large_image"')
  })

  it('declares valid JSON-LD naming the site and its origin', () => {
    const match = INDEX_HTML.match(
      /<script type="application\/ld\+json">([\s\S]*?)<\/script>/,
    )
    expect(match).not.toBeNull()

    // Parsed rather than pattern-matched: malformed JSON-LD is silently
    // ignored by every consumer, so a typo would otherwise never surface.
    const data = JSON.parse(match![1]) as Record<string, unknown>
    expect(data['@type']).toBe('WebSite')
    expect(data.url).toBe(`${SITE_ORIGIN}/`)
  })

  it('names no single example app, because it is served for all of them', () => {
    // The trap: writing the landing page's own copy into tags that every route
    // inherits. `src/seo/` is what makes a route specific.
    for (const app of LIVE_APPS) {
      expect(INDEX_HTML, `${app.name} is baked into the shared head`).not.toContain(app.name)
    }
  })

  it('still applies the theme before first paint', () => {
    // The pre-existing inline script must survive the tags landing around it,
    // or every visitor gets a flash of the wrong palette.
    expect(INDEX_HTML).toContain("localStorage.getItem('theme_preference')")
  })
})

describe('per-route metadata', () => {
  it('gives every live example app its own title and description', () => {
    const titles = new Set<string>()
    const descriptions = new Set<string>()

    for (const app of LIVE_APPS) {
      const meta = metaForPath(app.route)
      expect(meta.title).toContain(app.name)
      expect(meta.description).toBe(app.description)
      titles.add(meta.title)
      descriptions.add(meta.description)
    }

    // Distinctness is the property that matters, not merely presence: eleven
    // routes sharing one title is what a crawler reads as one page.
    expect(titles.size).toBe(LIVE_APPS.length)
    expect(descriptions.size).toBe(LIVE_APPS.length)
  })

  it('derives them from the catalogue rather than a second list', () => {
    // Mutating the catalogue at runtime must move the metadata with it. An
    // assertion on the literal name would pass against a hardcoded copy.
    const entry = exampleApps.find((app) => app.id === 'react_loop_example_app')!
    const original = entry.name
    try {
      Object.assign(entry, { name: 'Renamed Example' })
      expect(metaForPath(entry.route).title).toContain('Renamed Example')
    } finally {
      Object.assign(entry, { name: original })
    }
  })

  it('gives every route an absolute canonical URL on the deployed origin', () => {
    for (const app of exampleApps) {
      expect(metaForPath(app.route).canonical).toBe(`${SITE_ORIGIN}${app.route}`)
    }
    expect(metaForPath('/').canonical).toBe(`${SITE_ORIGIN}/`)
  })

  it('collapses a trailing slash rather than canonicalising two URLs', () => {
    // `/react` and `/react/` are one page to a visitor and two to a crawler,
    // which is the duplication a canonical link exists to resolve — so both
    // must point at the same one.
    expect(metaForPath('/react/').canonical).toBe(metaForPath('/react').canonical)
    expect(normalisePath('/')).toBe('/')
    expect(normalisePath('/react/')).toBe('/react')
  })

  it('falls back to the site description for an unknown path', () => {
    // A 404 that describes itself as a real page is worse than one that
    // describes the site.
    const meta = metaForPath('/no-such-route')

    expect(meta.title).toBe(DEFAULT_TITLE)
    expect(meta.description).toBe(DEFAULT_DESCRIPTION)
    expect(meta.canonical).toBe(`${SITE_ORIGIN}/`)
  })
})

describe('writing metadata into the document', () => {
  beforeEach(() => {
    document.head.innerHTML = ''
    document.title = ''
  })

  it('sets the title, description, canonical and social tags', () => {
    applyMeta(metaForPath('/react'))

    expect(document.title).toContain('ReAct')
    expect(
      document.head.querySelector('meta[name="description"]')?.getAttribute('content'),
    ).toBe(metaForPath('/react').description)
    expect(document.head.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(
      `${SITE_ORIGIN}/react`,
    )
    expect(
      document.head.querySelector('meta[property="og:url"]')?.getAttribute('content'),
    ).toBe(`${SITE_ORIGIN}/react`)
  })

  it('updates tags in place instead of appending a second copy', () => {
    // The failure this guards is cumulative and silent: a visitor who opens
    // four example apps would leave four descriptions in the head, and a
    // crawler picks whichever it likes.
    applyMeta(metaForPath('/react'))
    applyMeta(metaForPath('/collab'))
    applyMeta(metaForPath('/'))

    expect(document.head.querySelectorAll('meta[name="description"]')).toHaveLength(1)
    expect(document.head.querySelectorAll('link[rel="canonical"]')).toHaveLength(1)
    expect(document.head.querySelectorAll('meta[property="og:title"]')).toHaveLength(1)
  })

  it('matches on property for Open Graph and on name for the rest', () => {
    // og uses `property`, not `name`. Matching on the wrong attribute is how a
    // page ends up with two of each og tag rather than one updated one.
    applyMeta(metaForPath('/rag'))
    applyMeta(metaForPath('/rag'))

    expect(document.head.querySelectorAll('meta[property="og:description"]')).toHaveLength(1)
    expect(document.head.querySelectorAll('meta[name="twitter:description"]')).toHaveLength(1)
  })
})

describe('the sitemap and robots.txt', () => {
  it('lists exactly the landing page and every live example app', () => {
    const listed = [...SITEMAP.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1])

    expect(listed.sort()).toEqual(sitemapUrls().sort())
  })

  it('agrees with the catalogue in both directions', () => {
    // Same invariant, and same reasoning, as routes.test.tsx: an app listed in
    // one place and missing from the other is the failure, and it runs both
    // ways round.
    const listed = new Set(
      [...SITEMAP.matchAll(/<loc>([^<]+)<\/loc>/g)]
        .map((match) => match[1].replace(SITE_ORIGIN, ''))
        .filter((path) => path !== '/'),
    )
    const catalogue = new Set(LIVE_APPS.map((app) => app.route))

    expect([...listed].sort()).toEqual([...catalogue].sort())
  })

  it('never lists a coming-soon app', () => {
    // Submitting a placeholder screen for indexing advertises an app that does
    // not exist yet.
    for (const app of exampleApps.filter((entry) => entry.status === 'coming-soon')) {
      expect(SITEMAP).not.toContain(`${SITE_ORIGIN}${app.route}`)
    }
  })

  it('allows crawling, points at the sitemap, and keeps /health out', () => {
    expect(ROBOTS).toContain('User-agent: *')
    expect(ROBOTS).toContain('Allow: /')
    expect(ROBOTS).toContain(`Sitemap: ${SITE_ORIGIN}/sitemap.xml`)
    // An operational probe that hits the API and the database per request.
    expect(ROBOTS).toContain('Disallow: /health')
  })

  it('keeps /health out of the sitemap too', () => {
    expect(SITEMAP).not.toContain('/health')
  })
})

describe('analytics', () => {
  it('is switched off outside a production build', () => {
    // Vitest runs with PROD false. Asserted rather than assumed: a snippet
    // that counted developer traffic would be invisible until the numbers
    // were already wrong.
    expect(import.meta.env.PROD).toBe(false)
    expect(analyticsEnabled()).toBe(false)
  })

  it('loads no script and sends nothing when disabled', () => {
    document.head.innerHTML = ''
    delete window.gtag
    delete window.dataLayer

    initAnalytics()
    trackPageView('/react', 'ReAct')

    expect(document.head.querySelector('script[src*="googletagmanager"]')).toBeNull()
    expect(window.gtag).toBeUndefined()
    expect(window.dataLayer).toBeUndefined()
  })

  it('carries the measurement id the property expects', () => {
    expect(GA_MEASUREMENT_ID).toBe('G-PS571XRB2G')
  })

  it('is not hardcoded into index.html, where it could not be gated', () => {
    // Deliberate divergence from spec4.ai, which is a static site with no dev
    // server. A snippet in the HTML cannot be conditioned on the environment,
    // so every `npm run dev` session would be counted as a visitor.
    expect(INDEX_HTML).not.toContain('googletagmanager')
    expect(INDEX_HTML).not.toContain(GA_MEASUREMENT_ID)
  })
})

describe('keeping the head in step with the route', () => {
  /** A router double: `installSeo` takes the narrow shape, so no real one is needed. */
  function fakeRouter(pathname: string) {
    const subscribers: Array<(state: SeoRouterState) => void> = []
    const router = {
      state: {
        location: { pathname, key: pathname },
        navigation: { state: 'idle' },
      },
      subscribe(fn: (state: SeoRouterState) => void) {
        subscribers.push(fn)
        return () => subscribers.splice(subscribers.indexOf(fn), 1)
      },
      navigate(to: string, navigationState = 'idle') {
        const state: SeoRouterState = {
          location: { pathname: to, key: `${to}-1` },
          navigation: { state: navigationState },
        }
        for (const fn of [...subscribers]) fn(state)
      },
      get subscriberCount() {
        return subscribers.length
      },
    }
    return router
  }

  beforeEach(() => {
    document.head.innerHTML = ''
    document.title = ''
  })

  it('describes the landing route immediately, before any navigation', () => {
    const router = fakeRouter('/')
    installSeo(router)

    expect(document.title).toBe(DEFAULT_TITLE)
  })

  it('rewrites the head on each completed navigation', () => {
    const router = fakeRouter('/')
    installSeo(router)

    router.navigate('/react')
    expect(document.title).toContain('ReAct')
    expect(document.head.querySelector('link[rel="canonical"]')?.getAttribute('href')).toBe(
      `${SITE_ORIGIN}/react`,
    )

    router.navigate('/collab')
    expect(document.title).toContain('Collaboration')
  })

  it('waits for the navigation to settle', () => {
    // Subscribers fire when a navigation *starts* too, at which point the
    // location is already the new one while its lazy chunk is still loading.
    // Acting then would title the page after a screen the visitor may never
    // see, if the navigation is superseded.
    const router = fakeRouter('/')
    installSeo(router)

    router.navigate('/react', 'loading')
    expect(document.title).toBe(DEFAULT_TITLE)

    router.navigate('/react', 'idle')
    expect(document.title).toContain('ReAct')
  })

  it('ignores a repeated state change for the same location', () => {
    const router = fakeRouter('/')
    installSeo(router)
    router.navigate('/react')

    const before = document.head.querySelectorAll('meta').length
    router.navigate('/react')

    expect(document.head.querySelectorAll('meta').length).toBe(before)
  })

  it('returns an unsubscribe that actually detaches', () => {
    const router = fakeRouter('/')
    const stop = installSeo(router)
    expect(router.subscriberCount).toBe(1)

    stop()

    expect(router.subscriberCount).toBe(0)
  })
})

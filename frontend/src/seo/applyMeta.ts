// Built with Spec4 AI - https://spec4.ai
import type { PageMeta } from './siteMeta'
import { SITE_NAME } from './siteMeta'

/**
 * Write one route's metadata into the live document head.
 *
 * Separated from `siteMeta.ts` so *what a page says* stays pure and testable
 * while *how it reaches the DOM* is the only part that needs a document. Both
 * halves are exercised directly; neither needs a component rendered.
 *
 * **Tags are updated in place, never appended.** `index.html` already ships a
 * full set for the landing page, and a second `<meta name="description">`
 * leaves a crawler to pick one — so each helper finds the existing element by
 * selector and only creates one when it genuinely does not exist. Repeated
 * navigation therefore leaves exactly one of each tag.
 *
 * The Open Graph and Twitter tags are updated alongside the standard ones
 * because a link shared from a deep route should preview *that* example app
 * rather than the landing page. Crawlers that execute no JavaScript still see
 * `index.html`'s defaults, which is why those are written to be true of the
 * site as a whole.
 */

/**
 * Set (or create) a `<meta>` tag identified by a `name` attribute.
 *
 * @param name - The `name` attribute to match.
 * @param content - The value to write.
 */
function setNamedMeta(name: string, content: string): void {
  let tag = document.head.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)
  if (!tag) {
    tag = document.createElement('meta')
    tag.setAttribute('name', name)
    document.head.appendChild(tag)
  }
  tag.setAttribute('content', content)
}

/**
 * Set (or create) a `<meta>` tag identified by a `property` attribute.
 *
 * Open Graph uses `property` rather than `name`; matching on the wrong
 * attribute is how a page ends up with two of each og tag.
 *
 * @param property - The `property` attribute to match.
 * @param content - The value to write.
 */
function setPropertyMeta(property: string, content: string): void {
  let tag = document.head.querySelector<HTMLMetaElement>(`meta[property="${property}"]`)
  if (!tag) {
    tag = document.createElement('meta')
    tag.setAttribute('property', property)
    document.head.appendChild(tag)
  }
  tag.setAttribute('content', content)
}

/**
 * Set (or create) the canonical link.
 *
 * @param href - The absolute canonical URL.
 */
function setCanonical(href: string): void {
  let link = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]')
  if (!link) {
    link = document.createElement('link')
    link.setAttribute('rel', 'canonical')
    document.head.appendChild(link)
  }
  link.setAttribute('href', href)
}

/**
 * Apply a route's metadata to the document.
 *
 * @param meta - What this route should say, from `metaForPath`.
 */
export function applyMeta(meta: PageMeta): void {
  document.title = meta.title
  setNamedMeta('description', meta.description)
  setCanonical(meta.canonical)

  setPropertyMeta('og:title', meta.title)
  setPropertyMeta('og:description', meta.description)
  setPropertyMeta('og:url', meta.canonical)
  setPropertyMeta('og:site_name', SITE_NAME)

  setNamedMeta('twitter:title', meta.title)
  setNamedMeta('twitter:description', meta.description)
}

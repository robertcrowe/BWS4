// Built with Spec4 AI - https://spec4.ai
import { describe, expect, it } from 'vitest'

import viteConfig from '../vite.config'

/**
 * `vite.config.ts` sets `envDir: '..'` so the frontend reads the repo-root
 * `.env` — the single env file this project keeps, shared with the backend.
 * Without it Vite looked in `frontend/`, found nothing, and silently fell
 * back to the hardcoded defaults in `src/api/*`, so `VITE_API_BASE_URL` and
 * `VITE_SENTRY_DSN` were configured but never read in local development.
 *
 * That same file holds `DATABASE_URL` and the provider API keys. They stay
 * out of the bundle solely because Vite's default `envPrefix` exposes only
 * `VITE_`-prefixed variables. Widening or clearing `envPrefix` would publish
 * every backend secret in a downloadable asset — a one-word change that
 * reads as harmless in a diff, which is why it is pinned here.
 *
 * This asserts the configuration rather than `import.meta.env`, deliberately:
 * under Vitest, `import.meta.env` is merged with the whole `process.env`, so
 * inspecting it there measures the shell the tests ran in, not what ships.
 * The built output was additionally checked by hand — no non-`VITE_` value or
 * key from `.env` appears anywhere in `frontend/dist/`.
 */
describe('client environment exposure', () => {
  const config = viteConfig as { envDir?: string; envPrefix?: string | string[] }

  it('reads the single repo-root .env rather than a frontend-local one', () => {
    expect(config.envDir).toBe('..')
  })

  it('leaves envPrefix at the default so only VITE_ variables reach the client', () => {
    // Undefined means Vite's default, 'VITE_'. An explicit 'VITE_' is equally
    // safe; anything else would widen what the root .env publishes.
    const prefix = config.envPrefix

    if (prefix !== undefined) {
      const prefixes = Array.isArray(prefix) ? prefix : [prefix]
      expect(prefixes).toEqual(['VITE_'])
    } else {
      expect(prefix).toBeUndefined()
    }
  })
})

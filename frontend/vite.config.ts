// Built with Spec4 AI - https://spec4.ai
/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // The project keeps exactly one .env, at the repo root, shared by the
  // backend and the frontend. Vite otherwise looks in its own root
  // (frontend/), finds nothing, and silently falls back to the hardcoded
  // defaults in src/api/* — so VITE_API_BASE_URL and VITE_SENTRY_DSN were
  // configured but never read in local dev. Production was unaffected, since
  // Render supplies them as real environment variables, which Vite reads
  // regardless of envDir.
  //
  // Only VITE_-prefixed variables are exposed to client code, so the backend
  // secrets living in that same file (DATABASE_URL, the provider API keys)
  // are not bundled. There is a test pinning that.
  envDir: '..',
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    globals: true,
    // Vitest's 5s default is a poor fit for this suite: fourteen files each
    // stand up their own jsdom environment and run them in parallel, so under
    // contention a `userEvent` interaction can wait seconds for a turn. That
    // surfaced as unrelated files timing out at random once the suite grew --
    // a flake, not a failure, since every one of them passes in isolation.
    // Raised rather than worked around by trimming tests: a timeout catches a
    // hang, and 15s still catches one.
    testTimeout: 15_000,
  },
})

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
  },
})

// Built with Spec4 AI - https://spec4.ai
import * as Sentry from '@sentry/react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { router } from './routes'
import { installSeo } from './seo/installSeo'

// Error tracking is optional: with no VITE_SENTRY_DSN set (local dev, forks),
// Sentry is never initialized and the app runs exactly as before. When the DSN
// is present it reports to the same Sentry project as the backend's SENTRY_DSN.
const sentryDsn = import.meta.env.VITE_SENTRY_DSN

if (sentryDsn) {
  Sentry.init({
    dsn: sentryDsn,
    // browserTracing instruments fetch/XHR, so failed API requests to the
    // backend are captured alongside unhandled exceptions.
    integrations: [Sentry.browserTracingIntegration()],
    tracesSampleRate: 0.1,
    environment: import.meta.env.MODE,
  })
}

// Per-route titles, descriptions and canonical links, plus the GA4 page view
// each navigation should count as. Both no-op cleanly when switched off: the
// meta half always runs, the analytics half only in a production build with a
// measurement id — see `analytics.ts` for why dev traffic is kept out.
installSeo(router)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

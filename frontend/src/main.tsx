// Built with Spec4 AI - https://spec4.ai
import * as Sentry from '@sentry/react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

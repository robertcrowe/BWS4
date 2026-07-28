// Built with Spec4 AI - https://spec4.ai
import type { ReactNode } from 'react'
import { lazy, Suspense } from 'react'
import { createBrowserRouter } from 'react-router'

import { exampleApps } from './data/example-apps'

const LandingScreen = lazy(() =>
  import('./screens/landing/LandingScreen').then((module) => ({
    default: module.LandingScreen,
  })),
)
const ComingSoonScreen = lazy(() =>
  import('./screens/coming-soon/ComingSoonScreen').then((module) => ({
    default: module.ComingSoonScreen,
  })),
)
const HealthScreen = lazy(() =>
  import('./screens/health/HealthScreen').then((module) => ({ default: module.HealthScreen })),
)
const RagScreen = lazy(() =>
  import('./screens/rag/RagScreen').then((module) => ({ default: module.RagScreen })),
)
const ToolUseScreen = lazy(() =>
  import('./screens/tooluse/ToolUseScreen').then((module) => ({ default: module.ToolUseScreen })),
)

/** Wraps a lazy-loaded route element in the fallback every route shares while its chunk loads. */
function withSuspense(element: ReactNode) {
  return (
    <Suspense fallback={<p className="p-8 text-center text-gray-500">Loading...</p>}>
      {element}
    </Suspense>
  )
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: withSuspense(<LandingScreen />),
  },
  {
    path: '/health',
    element: withSuspense(<HealthScreen />),
  },
  {
    path: '/rag',
    element: withSuspense(<RagScreen />),
  },
  {
    path: '/tool-use',
    element: withSuspense(<ToolUseScreen />),
  },
  ...exampleApps
    .filter((app) => app.status === 'coming-soon')
    .map((app) => ({
      path: app.route,
      element: withSuspense(<ComingSoonScreen name={app.name} description={app.description} />),
    })),
])

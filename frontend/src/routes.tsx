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
const EmbeddingsScreen = lazy(() =>
  import('./screens/embeddings/EmbeddingsScreen').then((module) => ({
    default: module.EmbeddingsScreen,
  })),
)
const SingleCallScreen = lazy(() =>
  import('./screens/single-call/SingleCallScreen').then((module) => ({
    default: module.SingleCallScreen,
  })),
)
const ChainedCallsScreen = lazy(() =>
  import('./screens/chained-calls/ChainedCallsScreen').then((module) => ({
    default: module.ChainedCallsScreen,
  })),
)
const PlanningScreen = lazy(() =>
  import('./screens/planning/PlanningScreen').then((module) => ({
    default: module.PlanningScreen,
  })),
)
const OrchestratedScreen = lazy(() =>
  import('./screens/orchestrated/OrchestratedScreen').then((module) => ({
    default: module.OrchestratedScreen,
  })),
)
const CollabScreen = lazy(() =>
  import('./screens/collab/CollabScreen').then((module) => ({
    default: module.CollabScreen,
  })),
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
  {
    path: '/embeddings',
    element: withSuspense(<EmbeddingsScreen />),
  },
  {
    path: '/single-call',
    element: withSuspense(<SingleCallScreen />),
  },
  {
    path: '/chained-calls',
    element: withSuspense(<ChainedCallsScreen />),
  },
  {
    path: '/planning',
    element: withSuspense(<PlanningScreen />),
  },
  {
    path: '/orchestrated',
    element: withSuspense(<OrchestratedScreen />),
  },
  {
    path: '/collab',
    element: withSuspense(<CollabScreen />),
  },
  ...exampleApps
    .filter((app) => app.status === 'coming-soon')
    .map((app) => ({
      path: app.route,
      element: withSuspense(<ComingSoonScreen name={app.name} description={app.description} />),
    })),
])

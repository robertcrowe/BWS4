// Built with Spec4 AI - https://spec4.ai
import { useQuery } from '@tanstack/react-query'

import { fetchReactPresets } from './react'

/**
 * TanStack Query hook fetching the five curated multi-hop questions.
 *
 * A query rather than a mutation: it reads static server-side configuration,
 * spends no quota and calls no model. Marked permanently fresh for the same
 * reason as the orchestrated roster and the collaboration identity cards — the
 * catalogue is built from module constants compiled into the backend process,
 * so refetching returns byte-identical data. A redeploy replaces it, and a
 * redeploy reloads the page.
 *
 * @returns The query result backing the preset selector.
 */
export function useReactPresets() {
  return useQuery({
    queryKey: ['react', 'presets'],
    queryFn: fetchReactPresets,
    staleTime: Infinity,
  })
}

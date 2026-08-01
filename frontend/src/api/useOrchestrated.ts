// Built with Spec4 AI - https://spec4.ai
import { useQuery } from '@tanstack/react-query'

import { fetchRoster } from './orchestrated'

/**
 * TanStack Query hook fetching the specialist roster and curated presets.
 *
 * A query rather than a mutation, unlike this app's later coordinator and
 * specialist calls: it reads static server-side configuration, spends no quota,
 * and calls no model. Marked permanently fresh for the same reason as the
 * chained-calls plan query — the roster is built from module constants compiled
 * into the backend process, so refetching returns byte-identical data. A
 * redeploy replaces it, and a redeploy reloads the page.
 *
 * @returns The query result backing the roster panel and the preset chips.
 */
export function useRoster() {
  return useQuery({
    queryKey: ['orchestrated', 'roster'],
    queryFn: fetchRoster,
    staleTime: Infinity,
  })
}

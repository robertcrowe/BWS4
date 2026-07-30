// Built with Spec4 AI - https://spec4.ai
import { useMutation, useQuery } from '@tanstack/react-query'

import { fetchChainPlan, retryCritique, runChain } from './chainedCalls'

/**
 * TanStack Query hook fetching the description of both calls.
 *
 * A query, not a mutation: it reads fixed data, spends no quota, and is safe to
 * cache. Marked permanently fresh for the same reason as the single-call preset
 * query — the plan is built from constants compiled into the backend process,
 * so refetching would return byte-identical data.
 *
 * @returns The query result backing the upfront role descriptions.
 */
export function useChainPlan() {
  return useQuery({
    queryKey: ['chained-calls', 'plan'],
    queryFn: fetchChainPlan,
    staleTime: Infinity,
  })
}

/**
 * TanStack Query mutation hook running the full two-call chain.
 *
 * A mutation rather than a query, deliberately: the result is ephemeral, has no
 * stable resource key, and spends two units of a shared free-tier budget. Held
 * in a query cache it could be replayed or resurfaced against a *different*
 * story prompt — the phase's named risk — and here that would be worse than
 * stale data, because the story on screen would no longer be the story the
 * critique beside it was written about.
 *
 * `retry` is pinned to 0. The capability's escalation path is an explicit
 * manual retry of the failed step only; an automatic retry would silently spend
 * two more units on a chain the visitor never asked to re-run.
 *
 * @returns The mutation for submitting a story idea and observing the chain.
 */
export function useRunChain() {
  return useMutation({
    mutationFn: runChain,
    retry: 0,
  })
}

/**
 * TanStack Query mutation hook re-running only the critic call.
 *
 * Separate from `useRunChain` so the two have independent pending and error
 * states: a retry in flight must not make the completed story look like it is
 * being regenerated, which is the whole point of a scoped retry.
 *
 * @returns The mutation for retrying the critique against an existing story.
 */
export function useRetryCritique() {
  return useMutation({
    mutationFn: retryCritique,
    retry: 0,
  })
}

// Built with Spec4 AI - https://spec4.ai
import { useMutation } from '@tanstack/react-query'

import { fetchPlan, retrySynthesis } from './planning'

/**
 * TanStack Query mutation producing a plan for review.
 *
 * A mutation rather than a query, for the reasons every quota-spending call in
 * this repo is one: the result is ephemeral, has no stable resource key, and a
 * cached plan resurfacing against a *different* city would be worse than stale
 * data — the visitor would approve steps written for somewhere else.
 *
 * `retry` is pinned to 0. TanStack retries failed mutations by default in some
 * configurations, and an automatic retry here would silently spend a second
 * planner call the visitor never asked for. The relevant failures are a spent
 * hourly cap and a planner that could not produce a usable plan twice; neither
 * is fixed by trying again immediately.
 *
 * @returns The mutation backing the goal form.
 */
export function usePlanMutation() {
  return useMutation({
    mutationFn: fetchPlan,
    retry: 0,
  })
}

/**
 * TanStack Query mutation re-running only the synthesis step.
 *
 * Separate from the plan mutation so the two have independent pending and error
 * states: a retry in flight must not make the plan above it look like it is
 * being regenerated, which is the whole point of a scoped retry.
 *
 * @returns The mutation backing the retry-synthesis action.
 */
export function useRetrySynthesis() {
  return useMutation({
    mutationFn: retrySynthesis,
    retry: 0,
  })
}

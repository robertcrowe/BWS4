// Built with Spec4 AI - https://spec4.ai
import { useMutation, useQuery } from '@tanstack/react-query'

import { fetchSingleCallPresets, runSingleCall } from './singleCall'

/**
 * TanStack Query hook fetching the curated preset prompts.
 *
 * Marked permanently fresh: the set is versioned in-repo and bundled into the
 * backend process, so it cannot change while the page is open. Refetching
 * would return byte-identical data.
 *
 * @returns The query result backing the preset selector.
 */
export function useSingleCallPresets() {
  return useQuery({
    queryKey: ['single-call', 'presets'],
    queryFn: fetchSingleCallPresets,
    staleTime: Infinity,
  })
}

/**
 * TanStack Query mutation hook running one single call.
 *
 * A mutation rather than a query: the submission is visitor-triggered, spends
 * real free-tier quota, and must never be cached or replayed. `retry` is
 * pinned to 0 because the capability's escalation path is an explicit manual
 * retry — an automatic one would spend a second quota unit the visitor didn't
 * ask for, and would misrepresent a demo whose whole subject is that exactly
 * one call was made.
 *
 * @returns The mutation for submitting a prompt and observing the response.
 */
export function useSingleCall() {
  return useMutation({
    mutationFn: runSingleCall,
    retry: 0,
  })
}

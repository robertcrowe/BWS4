// Built with Spec4 AI - https://spec4.ai
import { useMutation, useQuery } from '@tanstack/react-query'

import { fetchPresets, placeCustomText } from './embeddings'

/**
 * TanStack Query hook fetching the preset examples and their coordinates.
 *
 * The presets never change for the life of the backend process — they are
 * derived from a bundled asset and a projection fitted once at startup — so
 * this is marked permanently fresh. Refetching would return byte-identical
 * data and re-render the plot for nothing.
 *
 * @returns The query result backing the semantic plot.
 */
export function useEmbeddingPresets() {
  return useQuery({
    queryKey: ['embeddings', 'presets'],
    queryFn: fetchPresets,
    staleTime: Infinity,
  })
}

/**
 * TanStack Query mutation hook placing custom text on the shared plot.
 *
 * Deliberately a mutation rather than a query, even though it reads rather
 * than writes: the submission is visitor-triggered, must not be cached or
 * replayed, and its result belongs to one specific submission. It also
 * touches no preset state — the presets query keeps `staleTime: Infinity`,
 * so submitting text never refetches or recomputes preset positions.
 *
 * @returns The mutation for submitting custom text and observing its placement.
 */
export function usePlaceCustomText() {
  return useMutation({
    mutationFn: placeCustomText,
  })
}

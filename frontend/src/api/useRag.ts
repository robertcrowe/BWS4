// Built with Spec4 AI - https://spec4.ai
import { useMutation, useQuery } from '@tanstack/react-query'

import { askRag, fetchDataset } from './rag'

/**
 * TanStack Query hook fetching the reference dataset's documents.
 *
 * @returns The query result for the dataset browser surface.
 */
export function useDatasetQuery() {
  return useQuery({
    queryKey: ['rag', 'dataset'],
    queryFn: fetchDataset,
  })
}

/**
 * TanStack Query mutation hook wrapping the RAG example app's ask endpoint.
 *
 * @returns The mutation for submitting a question and observing its result.
 */
export function useAskRagMutation() {
  return useMutation({
    mutationFn: askRag,
  })
}

// Built with Spec4 AI - https://spec4.ai
import { useMutation } from '@tanstack/react-query'

import { searchTool } from './tools'

/**
 * TanStack Query mutation hook wrapping the tool-use example app's search endpoint.
 *
 * @returns The mutation for submitting a search query and observing its result.
 */
export function useSearchMutation() {
  return useMutation({
    mutationFn: searchTool,
  })
}

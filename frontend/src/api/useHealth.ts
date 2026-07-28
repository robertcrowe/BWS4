// Built with Spec4 AI - https://spec4.ai
import { useQuery } from '@tanstack/react-query'

import { fetchHealth } from './health'

/**
 * TanStack Query hook wrapping the backend health check.
 *
 * @returns The query result for the backend's health status.
 */
export function useHealthQuery() {
  return useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    retry: false,
  })
}

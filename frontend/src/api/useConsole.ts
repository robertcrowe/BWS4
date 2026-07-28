// Built with Spec4 AI - https://spec4.ai
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { fetchConsoleStatus, sendConsoleTestRequest } from './console'

const STATUS_POLL_INTERVAL_MS = 5000

/**
 * TanStack Query hook polling the framework_services_console's live status
 * (usage limits + cross-app request log) so it stays current as other
 * example apps make shared-service calls.
 *
 * @returns The query result for the console's status.
 */
export function useConsoleStatusQuery() {
  return useQuery({
    queryKey: ['console', 'status'],
    queryFn: fetchConsoleStatus,
    refetchInterval: STATUS_POLL_INTERVAL_MS,
  })
}

/**
 * TanStack Query mutation hook wrapping the console's manual request tester,
 * refreshing the status query on success so the new usage/log rows show up
 * immediately rather than waiting for the next poll.
 *
 * @returns The mutation for sending a manual test request.
 */
export function useConsoleTestRequestMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: sendConsoleTestRequest,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['console', 'status'] })
    },
  })
}

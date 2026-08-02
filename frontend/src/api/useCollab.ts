// Built with Spec4 AI - https://spec4.ai
import { useQuery } from '@tanstack/react-query'

import { fetchIdentityCards } from './collab'

/**
 * TanStack Query hook fetching the three peer identity cards.
 *
 * A query rather than a mutation: it reads static server-side configuration,
 * spends no quota and calls no model. Marked permanently fresh for the same
 * reason as the orchestrated roster — the cards are built from module constants
 * compiled into the backend process, so refetching returns byte-identical data.
 * A redeploy replaces them, and a redeploy reloads the page.
 *
 * @returns The query result backing the identity-card panels.
 */
export function useIdentityCards() {
  return useQuery({
    queryKey: ['collab', 'identity-cards'],
    queryFn: fetchIdentityCards,
    staleTime: Infinity,
  })
}

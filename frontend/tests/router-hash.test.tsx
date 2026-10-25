// Built with Spec4 AI - https://spec4.ai
/**
 * The route descriptions on the page are byte for byte the block the router
 * received: the rendered text hashes to the server's SHA-256 of that block.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { createHash } from 'node:crypto'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { RouterApp } from '../src/apps/router/RouterApp'
import { HISTORY_WIRE, ROUTER_PRESETS, presetsWireBody } from './routerFixtures'

function sha256(text: string): string {
  return createHash('sha256').update(text, 'utf8').digest('hex')
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the route descriptions on the page', () => {
  it('hash to the server hash of the block the router received', async () => {
    const block = ROUTER_PRESETS.routeDescriptionsBlock
    const body = {
      ...presetsWireBody(ROUTER_PRESETS),
      route_descriptions_sha256: sha256(block),
    }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async (input: RequestInfo | URL) =>
        String(input).endsWith('/history')
          ? new Response(JSON.stringify(HISTORY_WIRE))
          : new Response(JSON.stringify(body)),
      ),
    )
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter>
          <RouterApp />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    const rendered = (await screen.findByTestId('route-descriptions-block')).textContent ?? ''
    expect(sha256(rendered)).toBe(body.route_descriptions_sha256)
    expect(screen.getByTestId('route-descriptions-sha256')).toHaveTextContent(
      body.route_descriptions_sha256,
    )
  })
})

// Built with Spec4 AI - https://spec4.ai
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchHealth } from '../src/api/health'
import { HealthScreen } from '../src/screens/health/HealthScreen'

vi.mock('../src/api/health', () => ({
  fetchHealth: vi.fn(),
}))

const mockedFetchHealth = vi.mocked(fetchHealth)

function renderScreen() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <HealthScreen />
    </QueryClientProvider>,
  )
}

describe('HealthScreen', () => {
  beforeEach(() => {
    mockedFetchHealth.mockReset()
  })

  it('shows the connected state when the API client resolves', async () => {
    mockedFetchHealth.mockResolvedValue({ status: 'ok', db: 'connected' })

    renderScreen()

    expect(await screen.findByText('Backend: connected')).toBeInTheDocument()
  })

  it('shows an error state when the API client rejects', async () => {
    mockedFetchHealth.mockRejectedValue(new Error('network error'))

    renderScreen()

    expect(await screen.findByRole('alert')).toHaveTextContent('Backend: error')
  })
})

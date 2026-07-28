// Built with Spec4 AI - https://spec4.ai
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchConsoleStatus, sendConsoleTestRequest } from '../src/api/console'
import { ConsoleApp } from '../src/screens/console/ConsoleApp'

vi.mock('../src/api/console', () => ({
  fetchConsoleStatus: vi.fn(),
  sendConsoleTestRequest: vi.fn(),
}))

const mockedFetchConsoleStatus = vi.mocked(fetchConsoleStatus)
const mockedSendConsoleTestRequest = vi.mocked(sendConsoleTestRequest)

function renderConsoleApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ConsoleApp />
    </QueryClientProvider>,
  )
}

describe('ConsoleApp', () => {
  beforeEach(() => {
    mockedFetchConsoleStatus.mockReset()
    mockedSendConsoleTestRequest.mockReset()
  })

  it('renders usage limits and at least one log entry from a mocked console status response', async () => {
    mockedFetchConsoleStatus.mockResolvedValue({
      usage_limits: [
        { capability: 'generation', used: 42, cap: 100, window_start: '2026-07-28' },
        { capability: 'representation', used: 15, cap: 50, window_start: '2026-07-28' },
      ],
      log_entries: [
        {
          app_name: 'RAG Example App',
          capability: 'generation',
          summary: 'Generated a grounded RAG answer',
          timestamp: '2026-07-26T12:00:00Z',
        },
      ],
    })

    renderConsoleApp()

    expect(await screen.findByText('42 / 100')).toBeInTheDocument()
    expect(screen.getByText('15 / 50')).toBeInTheDocument()
    expect(screen.getByText('Generated a grounded RAG answer')).toBeInTheDocument()
    expect(screen.getByText('RAG Example App')).toBeInTheDocument()
  })

  it('shows the empty-log state when no requests have been made yet', async () => {
    mockedFetchConsoleStatus.mockResolvedValue({ usage_limits: [], log_entries: [] })

    renderConsoleApp()

    expect(await screen.findByText(/no requests yet/i)).toBeInTheDocument()
  })
})

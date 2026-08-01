// Built with Spec4 AI - https://spec4.ai
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { askRag, fetchDataset } from '../src/api/rag'
import { RagApp } from '../src/apps/rag/RagApp'

vi.mock('../src/api/rag', () => ({
  askRag: vi.fn(),
  fetchDataset: vi.fn(),
}))

const mockedAskRag = vi.mocked(askRag)
const mockedFetchDataset = vi.mocked(fetchDataset)

function renderRagApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <RagApp />
    </QueryClientProvider>,
  )
}

async function submitQuestion(question: string) {
  const user = userEvent.setup()
  const input = screen.getByPlaceholderText(/when did voyager 1 launch/i)
  await user.type(input, question)
  await user.click(screen.getByRole('button', { name: 'Ask' }))
}

describe('RagApp', () => {
  beforeEach(() => {
    mockedAskRag.mockReset()
    mockedFetchDataset.mockReset()
    mockedFetchDataset.mockResolvedValue([
      { title: 'Voyager 1', text: 'Voyager 1 launched on September 5, 1977.' },
    ])
  })

  it('renders the answer and a retrieved passage with a similarity score for a grounded response', async () => {
    mockedAskRag.mockResolvedValue({
      answer: 'Voyager 1 launched in 1977 [1].',
      retrieved_passages: [
        {
          passage_id: 'voyager-1-1',
          source_title: 'Voyager 1',
          text_excerpt: 'Voyager 1 launched on September 5, 1977.',
          similarity_score: 0.82,
        },
      ],
      status: 'grounded',
      cited_passages: [1],
      unresolved_citations: [],
    })

    renderRagApp()
    await submitQuestion('When did Voyager 1 launch?')

    expect(await screen.findByText('Voyager 1 launched in 1977 [1].')).toBeInTheDocument()
    expect(screen.getByText(/match score: 0\.82/)).toBeInTheDocument()
    expect(screen.getByText(/Grounded in 1 of 1 retrieved passage/)).toBeInTheDocument()
    expect(screen.getByText('cited')).toBeInTheDocument()
  })

  it('renders a markdown answer as formatted elements', async () => {
    // `answer_v2.md` asks for prose with bracketed citations and says nothing
    // about formatting, so models answer with lists and bold often enough that
    // printing the raw syntax was a visible defect.
    mockedAskRag.mockResolvedValue({
      answer: 'It launched in **1977** [1]. Key facts:\n\n- Still transmitting\n- Now interstellar',
      retrieved_passages: [],
      status: 'grounded',
      cited_passages: [1],
      unresolved_citations: [],
    })

    renderRagApp()
    await submitQuestion('When did Voyager 1 launch?')

    expect((await screen.findByText('1977')).tagName).toBe('STRONG')
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    // The citation marker still reaches the visitor literally — the passage
    // cards are keyed to it.
    expect(screen.getByText(/\[1\]/)).toBeInTheDocument()
  })

  it('renders the graceful no-strong-match message instead of a fabricated answer', async () => {
    mockedAskRag.mockResolvedValue({
      answer: 'No strong match found in this dataset for that question.',
      retrieved_passages: [],
      status: 'low_relevance',
      cited_passages: [],
      unresolved_citations: [],
    })

    renderRagApp()
    await submitQuestion("What's the best pizza topping?")

    expect(await screen.findByText(/no strong match found in this dataset/i)).toBeInTheDocument()
    expect(screen.getByText(/low confidence/i)).toBeInTheDocument()
  })

  it('does not claim grounding when passages scored well but the answer cites none', async () => {
    // The case the similarity score alone cannot catch: an on-topic question
    // the dataset does not answer. The passage scores 0.46, comfortably above
    // the threshold, so the old badge called this grounded.
    mockedAskRag.mockResolvedValue({
      answer: 'These passages do not say who the first woman in space was.',
      retrieved_passages: [
        {
          passage_id: 'yuri-gagarin-1',
          source_title: 'Yuri Gagarin',
          text_excerpt: 'Yuri Gagarin became the first human to journey into outer space.',
          similarity_score: 0.46,
        },
      ],
      status: 'unsupported',
      cited_passages: [],
      unresolved_citations: [],
    })

    renderRagApp()
    await submitQuestion('Who was the first woman in space?')

    expect(await screen.findByText(/answer cites no retrieved passage/i)).toBeInTheDocument()
    expect(screen.queryByText(/^Grounded in/)).not.toBeInTheDocument()
    expect(screen.getByText('retrieved, not cited')).toBeInTheDocument()
  })

  it('flags a citation that matches no retrieved passage', async () => {
    mockedAskRag.mockResolvedValue({
      answer: 'Voyager 1 launched in 1977 [4].',
      retrieved_passages: [
        {
          passage_id: 'voyager-1-1',
          source_title: 'Voyager 1',
          text_excerpt: 'Voyager 1 launched on September 5, 1977.',
          similarity_score: 0.82,
        },
      ],
      status: 'unsupported',
      cited_passages: [],
      unresolved_citations: [4],
    })

    renderRagApp()
    await submitQuestion('When did Voyager 1 launch?')

    expect(await screen.findByText(/invented by the model/i)).toBeInTheDocument()
    expect(screen.getByText(/\[4\], which/)).toBeInTheDocument()
  })
})

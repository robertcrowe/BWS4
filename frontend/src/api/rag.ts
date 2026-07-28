// Built with Spec4 AI - https://spec4.ai
export interface RetrievedPassage {
  passage_id: string
  source_title: string
  text_excerpt: string
  similarity_score: number
}

export interface AskRagResponse {
  answer: string
  retrieved_passages: RetrievedPassage[]
  status: 'grounded' | 'low_relevance'
}

export interface DatasetDocument {
  title: string
  text: string
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/**
 * Fetch the reference dataset's documents for the dataset browser surface.
 *
 * @returns The dataset's documents.
 * @throws Error if the backend responds with a non-2xx status.
 */
export async function fetchDataset(): Promise<DatasetDocument[]> {
  const response = await fetch(`${API_BASE_URL}/api/rag/dataset`)

  if (!response.ok) {
    throw new Error(`Fetching the dataset failed with status ${response.status}`)
  }

  const body = (await response.json()) as { documents: DatasetDocument[] }
  return body.documents
}

/**
 * Ask a question via the RAG example app's retrieval-augmented generation endpoint.
 *
 * @param userQuestion - The visitor's natural-language question.
 * @returns The generated answer and the passages it was grounded in.
 * @throws Error if the backend responds with a non-2xx status (e.g. the
 * shared generation capability is unavailable).
 */
export async function askRag(userQuestion: string): Promise<AskRagResponse> {
  const response = await fetch(`${API_BASE_URL}/api/rag/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_question: userQuestion }),
  })

  if (!response.ok) {
    throw new Error(`Asking the RAG example app failed with status ${response.status}`)
  }

  return (await response.json()) as AskRagResponse
}

// Built with Spec4 AI - https://spec4.ai
export interface RetrievedPassage {
  passage_id: string
  source_title: string
  text_excerpt: string
  similarity_score: number
}

/**
 * `low_relevance` means retrieval never cleared the similarity threshold, so
 * no answer was generated. `grounded` and `unsupported` both mean the model
 * ran: they differ in whether its answer cited any retrieved passage. The
 * backend audits the answer's `[N]` markers to decide, so this is a property
 * of the answer rather than a restatement of the similarity score.
 */
export type RagStatus = 'grounded' | 'unsupported' | 'low_relevance'

export interface AskRagResponse {
  answer: string
  retrieved_passages: RetrievedPassage[]
  status: RagStatus
  /** 1-based positions in `retrieved_passages` the answer actually cites. */
  cited_passages: number[]
  /** Citation markers in the answer that match no retrieved passage. */
  unresolved_citations: number[]
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
 * The backend's own `detail` is surfaced rather than swallowed behind a status
 * code. That mattered less when every failure here meant "the provider is
 * down"; it matters now that a question can be refused by the shared safety
 * gate, because the whole value of that refusal is the sentence telling the
 * visitor they can reword and try again.
 *
 * @param userQuestion - The visitor's natural-language question.
 * @returns The generated answer and the passages it was grounded in.
 * @throws Error carrying the backend's explanation, or a status-code fallback
 * when it did not send one.
 */
export async function askRag(userQuestion: string): Promise<AskRagResponse> {
  const response = await fetch(`${API_BASE_URL}/api/rag/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_question: userQuestion }),
  })

  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? (body as { detail: unknown }).detail
        : null

    throw new Error(
      typeof detail === 'string' && detail
        ? detail
        : `Asking the RAG example app failed with status ${response.status}`,
    )
  }

  return (await response.json()) as AskRagResponse
}

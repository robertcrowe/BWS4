// Built with Spec4 AI - https://spec4.ai
import { DatasetBrowser } from './DatasetBrowser'
import { QuestionAnswer } from './QuestionAnswer'

/**
 * The RAG example app: the reference dataset browser alongside the
 * question/answer surface, so a visitor can inspect the retrieval corpus
 * before (or while) watching a question get answered from it.
 */
export function RagApp() {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[320px_1fr]">
      <DatasetBrowser />
      <QuestionAnswer />
    </div>
  )
}

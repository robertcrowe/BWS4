// Built with Spec4 AI - https://spec4.ai
import { useState } from 'react'

import { useDatasetQuery } from '../../api/useRag'

/**
 * rag_dataset_browser surface: lists the reference dataset's documents, each
 * collapsible to its full text, so a visitor can see exactly what the
 * retriever draws from before asking a question.
 */
export function DatasetBrowser() {
  const { data: documents, isPending, isError } = useDatasetQuery()
  const [openTitles, setOpenTitles] = useState<Set<string>>(new Set())

  function toggle(title: string) {
    setOpenTitles((previous) => {
      const next = new Set(previous)
      if (next.has(title)) {
        next.delete(title)
      } else {
        next.add(title)
      }
      return next
    })
  }

  return (
    <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 p-5">
      <h4 className="mb-3 text-sm font-semibold text-gray-900 dark:text-gray-100">
        Reference Dataset{documents ? ` (${documents.length} documents)` : ''}
      </h4>
      <p className="mb-4 text-xs text-gray-500">
        A small, topic-limited public dataset of space exploration facts — questions outside
        this topic won&apos;t find a strong match.
      </p>

      {isPending && <p className="text-sm text-gray-500">Loading dataset…</p>}
      {isError && <p className="text-sm text-red-600 dark:text-red-400">Could not load the reference dataset.</p>}

      {documents?.map((doc) => {
        const isOpen = openTitles.has(doc.title)
        return (
          <div key={doc.title} className="mb-2.5 overflow-hidden rounded-lg border border-gray-200 dark:border-gray-800">
            <button
              type="button"
              onClick={() => toggle(doc.title)}
              className="flex w-full items-center justify-between bg-gray-100 dark:bg-gray-800/60 px-3.5 py-3 text-left"
              aria-expanded={isOpen}
            >
              <strong className="text-[13.5px] font-medium text-gray-900 dark:text-gray-100">{doc.title}</strong>
              <span
                className={`text-gray-500 transition-transform ${isOpen ? 'rotate-90' : ''}`}
                aria-hidden="true"
              >
                ▶
              </span>
            </button>
            {isOpen && (
              <div className="max-h-60 overflow-y-auto px-3.5 py-3 text-[13px] text-gray-600 dark:text-gray-400">
                <p>{doc.text}</p>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

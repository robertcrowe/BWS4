// Built with Spec4 AI - https://spec4.ai
import { Markdown } from '../../components/Markdown'
import type { MergedAnswerEvent, Specialist } from '../../api/orchestrated'

/**
 * The fan-in: one merged answer, and the note on how the two answers related.
 *
 * The merged text goes through the shared `Markdown` wrapper and never through
 * `dangerouslySetInnerHTML`. This surface is public, unauthenticated, and shows
 * model output derived from free-form visitor text — rendering it as HTML would
 * be a real injection path, not a theoretical one.
 *
 * The note is a **distinct panel beside the answer** rather than folded into
 * it, because it says something different: the answer is the content, the note
 * is the relationship between the two sources. Its contradictions have already
 * survived a server-side traceability check, so every quote shown here was
 * found in the answer it is attributed to — a fabricated conflict never reaches
 * this component.
 */
export interface MergedAnswerPanelProps {
  merged: MergedAnswerEvent
  specialists: Specialist[]
}

function labelFor(specialists: Specialist[], id: string | null): string {
  if (!id) {
    return 'a specialist'
  }
  return specialists.find((entry) => entry.id === id)?.displayName ?? id
}

/**
 * Render the merged answer and its disagreement note.
 *
 * @param props - The merged answer event and the roster for labels.
 * @returns The fan-in panel.
 */
export function MergedAnswerPanel({ merged, specialists }: MergedAnswerPanelProps) {
  const note = merged.disagreement_note
  const sources = merged.sources_used.map((id) => labelFor(specialists, id)).join(' + ')

  return (
    <section
      data-testid="merged-answer"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <p className="font-mono text-xs text-violet-600 dark:text-violet-400">
        ↳ fan-in complete: {merged.sources_used.length} specialist answer
        {merged.sources_used.length === 1 ? '' : 's'} → 1 merged answer
      </p>

      <div className="mt-3 grid gap-5 lg:grid-cols-[1.6fr_1fr]">
        <div>
          <h3 className="mb-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
            Merged answer
          </h3>
          <Markdown data-testid="merged-text">{merged.text}</Markdown>
        </div>

        <aside
          data-testid="disagreement-note"
          className="rounded-xl border border-gray-200 bg-gray-50 p-4 dark:border-gray-800 dark:bg-gray-950"
        >
          <h4 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
            How the two specialists compared
          </h4>

          <p className="mt-2 text-xs leading-relaxed text-gray-600 dark:text-gray-400">
            {note.summary}
          </p>

          {note.comparable ? (
            <div className="mt-3 space-y-3">
              {note.agreements.length > 0 ? (
                <div>
                  <p className="text-[10px] font-semibold tracking-wide text-emerald-600 uppercase dark:text-emerald-400">
                    Agree
                  </p>
                  <ul className="mt-1 space-y-1">
                    {note.agreements.map((item) => (
                      <li key={item} className="text-xs leading-relaxed text-gray-600 dark:text-gray-400">
                        • {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              {note.complements.length > 0 ? (
                <div>
                  <p className="text-[10px] font-semibold tracking-wide text-violet-600 uppercase dark:text-violet-400">
                    Complement
                  </p>
                  <ul className="mt-1 space-y-1">
                    {note.complements.map((item) => (
                      <li key={item} className="text-xs leading-relaxed text-gray-600 dark:text-gray-400">
                        • {item}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <div>
                <p className="text-[10px] font-semibold tracking-wide text-amber-600 uppercase dark:text-amber-400">
                  Contradict
                </p>
                {note.contradictions.length === 0 ? (
                  <p className="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-500">
                    No conflict found. The two were briefed onto different angles, so
                    agreement on the parts they share is the expected result.
                  </p>
                ) : (
                  <ul className="mt-1 space-y-2">
                    {note.contradictions.map((item) => (
                      <li
                        key={`${item.claim_a}|${item.claim_b}`}
                        className="text-xs leading-relaxed text-gray-600 dark:text-gray-400"
                      >
                        <span className="font-medium text-gray-800 dark:text-gray-200">
                          {labelFor(specialists, item.specialist_a)}:
                        </span>{' '}
                        &ldquo;{item.claim_a}&rdquo;
                        <br />
                        <span className="font-medium text-gray-800 dark:text-gray-200">
                          {labelFor(specialists, item.specialist_b)}:
                        </span>{' '}
                        &ldquo;{item.claim_b}&rdquo;
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          ) : null}
        </aside>
      </div>

      <p className="mt-4 border-t border-gray-100 pt-3 text-[11px] leading-relaxed text-gray-400 dark:border-gray-800 dark:text-gray-500">
        Call budget used: 1 coordinator + 2 specialists (parallel), with the merge folded into
        the coordinator&rsquo;s closing turn = {merged.model_call_count} total. Both source
        answers remain on screen above{sources ? ` (${sources})` : ''}. AI-generated
        demonstration output, not advice.
      </p>
    </section>
  )
}

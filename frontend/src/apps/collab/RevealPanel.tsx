// Built with Spec4 AI - https://spec4.ai
import { useState } from 'react'

import { Markdown } from '../../components/Markdown'
import type { RevealParty } from '../../api/collab'
import type { RunState } from './runState'

/**
 * `collab_private_reveal`: what each party was actually carrying.
 *
 * **The table renders before the narration arrives, from the run's own record.**
 * Opening and final values, and whether a party moved, are facts the client
 * already has the moment the final bids land — so the panel is populated
 * immediately and the prose fills in when the explanation call completes. That
 * ordering matters because these panels come *after* six stages of waiting; a
 * spinner here is the worst thing the screen could show.
 *
 * Per-party detail is collapsed behind each headline. The reveal is supposed to
 * clarify a dense run, and eight axis explanations opened at once would add to
 * the density it is meant to relieve.
 *
 * A template-generated narration is **badged**. It is assembled from arithmetic
 * rather than written, so it says less — passing it off as the model's prose
 * would be the same defect this project keeps removing elsewhere.
 */

const STANCE_COPY: Record<string, string> = {
  conceded: 'moved',
  held_firm: 'held',
}

const CONSTRAINT_COPY: Record<string, string> = {
  cost_floor: 'cost floor',
  capacity_ceiling: 'capacity ceiling',
  delivery_capability: 'fastest delivery',
  warranty_liability_limit: 'warranty limit',
  budget_ceiling: 'budget ceiling',
  batna: 'fallback option',
}

/** Props for {@link RevealPanel}. */
export interface RevealPanelProps {
  state: RunState
}

function PartyBlock({ party }: { party: RevealParty }) {
  const [open, setOpen] = useState(false)

  return (
    <div
      data-testid={`reveal-party-${party.party_id}`}
      className="rounded-xl border border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-gray-950"
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-start gap-2 px-3.5 py-3 text-left hover:bg-gray-100 dark:hover:bg-gray-900"
      >
        <span className="text-[13px] font-semibold text-gray-900 capitalize dark:text-gray-100">
          {party.party_id}
        </span>
        <span className="flex-1 text-xs text-gray-600 dark:text-gray-400">
          {party.headline}
        </span>
        <span
          aria-hidden="true"
          className={`text-[10px] text-gray-400 transition-transform ${open ? 'rotate-90' : ''}`}
        >
          ▶
        </span>
      </button>

      {open && (
        <dl className="border-t border-gray-200 px-3.5 py-3 dark:border-gray-800">
          {party.axes.map((axis) => (
            <div key={axis.axis} className="mb-3 last:mb-0">
              <dt className="font-mono text-[10px] uppercase tracking-wide text-gray-500">
                {axis.axis} · {STANCE_COPY[axis.stance] ?? axis.stance}{' '}
                {axis.opening_value} → {axis.final_value}
                {axis.binding_constraint && (
                  <span className="ml-2 rounded-full border border-amber-500/50 px-1.5 py-0.5 text-amber-600 dark:text-amber-400">
                    at its {CONSTRAINT_COPY[axis.binding_constraint] ?? axis.binding_constraint}
                  </span>
                )}
              </dt>
              <dd className="mt-1">
                <Markdown>{axis.explanation}</Markdown>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

/**
 * Render the post-award unsealing.
 *
 * @param props - The current run state.
 * @returns The reveal panel, or null before any bids have completed.
 */
export function RevealPanel({ state }: RevealPanelProps) {
  const sellers = state.sellerOrder.filter((id) => state.columns[id]?.final)
  if (sellers.length === 0) {
    return null
  }

  const sealed = state.award === null

  return (
    <section
      data-testid="reveal-panel"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          What each party was actually carrying
        </h3>
        {state.reveal?.fallback_generated && (
          <span
            data-testid="reveal-fallback-badge"
            className="rounded-full border border-amber-500/50 px-2 py-0.5 font-mono text-[10px] text-amber-600 dark:text-amber-400"
          >
            generated from the record, not written
          </span>
        )}
      </div>

      {sealed ? (
        <p
          data-testid="reveal-sealed"
          className="mt-3 rounded-xl border border-gray-200 bg-gray-50 p-3 text-xs text-gray-500 dark:border-gray-800 dark:bg-gray-950 dark:text-gray-400"
        >
          🔒 Sealed. Each party&rsquo;s private position is unsealed only once the
          award has been made — the server will not produce this earlier, because
          the whole point of the run is that nobody could see it during the
          bidding.
        </p>
      ) : (
        <>
          {/* The table renders from the run's own record, before any narration
              arrives. A visitor never sees an empty panel here. */}
          <div data-testid="reveal-table" className="mt-3 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-200 text-left dark:border-gray-800">
                  <th className="py-2 pr-2 font-medium text-gray-500">Supplier</th>
                  <th className="py-2 pr-2 font-medium text-gray-500">Term</th>
                  <th className="py-2 pr-2 font-medium text-gray-500">Opening</th>
                  <th className="py-2 pr-2 font-medium text-gray-500">Final</th>
                  <th className="py-2 font-medium text-gray-500">Moved?</th>
                </tr>
              </thead>
              <tbody>
                {sellers.flatMap((sellerId) => {
                  const column = state.columns[sellerId]
                  const rows: [string, number, number][] = [
                    ['price', column.opening?.unitPrice ?? 0, column.final?.unitPrice ?? 0],
                    [
                      'delivery',
                      column.opening?.deliveryDays ?? 0,
                      column.final?.deliveryDays ?? 0,
                    ],
                    ['quantity', column.opening?.quantity ?? 0, column.final?.quantity ?? 0],
                    [
                      'warranty',
                      column.opening?.warrantyMonths ?? 0,
                      column.final?.warrantyMonths ?? 0,
                    ],
                  ]
                  return rows.map(([axis, opening, final]) => (
                    <tr
                      key={`${sellerId}-${axis}`}
                      className="border-b border-gray-100 last:border-0 dark:border-gray-800"
                    >
                      <td className="py-1.5 pr-2 text-gray-600 capitalize dark:text-gray-400">
                        {sellerId}
                      </td>
                      <td className="py-1.5 pr-2 text-gray-600 dark:text-gray-400">{axis}</td>
                      <td className="py-1.5 pr-2 font-mono text-gray-500">{opening}</td>
                      <td className="py-1.5 pr-2 font-mono text-gray-800 dark:text-gray-200">
                        {final}
                      </td>
                      <td className="py-1.5 text-gray-500">
                        {opening === final ? 'held' : 'moved'}
                      </td>
                    </tr>
                  ))
                })}
              </tbody>
            </table>
          </div>

          {state.reveal ? (
            <div data-testid="reveal-narration" className="mt-4 space-y-2">
              {state.reveal.parties.map((party) => (
                <PartyBlock key={party.party_id} party={party} />
              ))}
            </div>
          ) : (
            <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
              Unsealing each party&rsquo;s reasoning…
            </p>
          )}
        </>
      )}
    </section>
  )
}

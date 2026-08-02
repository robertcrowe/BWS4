// Built with Spec4 AI - https://spec4.ai
import { Fragment } from 'react'

import type { ColumnBid, RunState } from './runState'

/**
 * Opening → best-and-final, per seller, across the four axes.
 *
 * The trade-off the buyer had to weigh is arithmetic, and prose is a bad way to
 * read arithmetic. Four rows and a column per supplier make "cheaper but only
 * 180 units" legible without reading anyone's notes — which is what the
 * capability means by collapsing the run to a term-by-term diff.
 *
 * Movement is marked rather than merely shown: a number that improved between
 * rounds is what a concession *is*, and spotting it by comparing two columns by
 * eye is work the table can do instead.
 */

const AXES: { key: keyof ColumnBid; label: string; lowerIsBetter: boolean }[] = [
  { key: 'unitPrice', label: 'Unit price', lowerIsBetter: true },
  { key: 'deliveryDays', label: 'Delivery (days)', lowerIsBetter: true },
  { key: 'quantity', label: 'Quantity', lowerIsBetter: false },
  { key: 'warrantyMonths', label: 'Warranty (months)', lowerIsBetter: false },
]

/** Props for {@link DiffTable}. */
export interface DiffTableProps {
  state: RunState
}

function improved(
  axis: (typeof AXES)[number],
  opening: ColumnBid | null,
  final: ColumnBid | null,
): boolean {
  if (!opening || !final) {
    return false
  }
  const before = opening[axis.key] as number
  const after = final[axis.key] as number
  return axis.lowerIsBetter ? after < before : after > before
}

/**
 * Render the term-by-term movement table.
 *
 * @param props - The current run state.
 * @returns The diff table, or null until at least one final bid has landed.
 */
export function DiffTable({ state }: DiffTableProps) {
  const sellers = state.sellerOrder.filter((id) => state.columns[id]?.final)
  if (sellers.length === 0) {
    return null
  }

  return (
    <section
      data-testid="diff-table"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        Term by term: opening bid → best and final
      </h3>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-800">
              <th className="py-2 text-left font-medium text-gray-500">Term</th>
              {sellers.map((sellerId) => (
                <th
                  key={sellerId}
                  colSpan={2}
                  className="py-2 text-left font-medium text-gray-700 capitalize dark:text-gray-300"
                >
                  {sellerId}
                </th>
              ))}
            </tr>
            <tr className="border-b border-gray-200 dark:border-gray-800">
              <th />
              {sellers.map((sellerId) => (
                <Fragment key={sellerId}>
                  <th className="py-1 text-left font-mono text-[10px] font-normal text-gray-400">
                    opening
                  </th>
                  <th className="py-1 text-left font-mono text-[10px] font-normal text-gray-400">
                    final
                  </th>
                </Fragment>
              ))}
            </tr>
          </thead>
          <tbody>
            {AXES.map((axis) => (
              <tr
                key={axis.key}
                className="border-b border-gray-100 last:border-0 dark:border-gray-800"
              >
                <td className="py-1.5 text-gray-600 dark:text-gray-400">{axis.label}</td>
                {sellers.map((sellerId) => {
                  const column = state.columns[sellerId]
                  const moved = improved(axis, column.opening, column.final)
                  return (
                    <Fragment key={sellerId}>
                      <td className="py-1.5 font-mono text-gray-500">
                        {column.opening ? String(column.opening[axis.key]) : '—'}
                      </td>
                      <td
                        data-improved={moved ? 'true' : 'false'}
                        className={`py-1.5 font-mono ${
                          moved
                            ? 'font-semibold text-emerald-700 dark:text-emerald-400'
                            : 'text-gray-800 dark:text-gray-200'
                        }`}
                      >
                        {column.final ? String(column.final[axis.key]) : '—'}
                      </td>
                    </Fragment>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-gray-400 dark:text-gray-500">
        Green marks a term that improved after the buyer&rsquo;s counter-offer. A
        supplier holding firm is not a failure — it usually means its sealed position
        had no room on that axis, which the end-of-run reveal will show.
      </p>
    </section>
  )
}

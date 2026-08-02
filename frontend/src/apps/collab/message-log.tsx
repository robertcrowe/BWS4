// Built with Spec4 AI - https://spec4.ai
import { useState } from 'react'

import type { PeerMessageRow } from '../../api/collab'
import type { RunState } from './runState'

/**
 * `collab_message_log`: the evidence, not the assertion.
 *
 * Every other surface on this screen *tells* the visitor that the two sellers
 * cannot see each other. This one lets them check: every envelope the run
 * routed, in sequence order, with exactly one sender and one recipient per row.
 * The absence of any seller→seller row is the claim, and it is visible at a
 * glance rather than asserted in a sentence.
 *
 * Rows come from the server's own `bus.log()` — the same source that writes
 * `peer_messages` — rather than being tallied from the events this client
 * happened to receive. A browser-side count would only prove what the browser
 * was shown, which is not evidence about what the server did.
 *
 * ## Deliberately plain
 *
 * A hand-rolled Tailwind table. **No JSON-viewer dependency, no
 * syntax-highlighting library, no copy-to-clipboard** — the phase rules all
 * three out, and a dense, boring table is the right shape for something whose
 * job is to be scanned for an absence.
 *
 * Collapsed by default. The log is corroboration for a visitor who wants it,
 * not the first thing to read; the capability lists the six-stage flow's
 * density as a likelihood-high failure mode.
 */

/** Props for {@link MessageLog}. */
export interface MessageLogProps {
  state: RunState
}

function Row({ row, sellers }: { row: PeerMessageRow; sellers: string[] }) {
  const [open, setOpen] = useState(false)
  const sellerToSeller =
    sellers.includes(row.sender) && sellers.includes(row.recipient)

  return (
    <>
      <tr
        data-testid={`log-row-${row.sequence}`}
        data-seller-to-seller={sellerToSeller ? 'true' : 'false'}
        className="border-b border-gray-100 dark:border-gray-800"
      >
        <td className="py-2 pr-2 font-mono text-gray-400">{row.sequence}</td>
        <td className="py-2 pr-2 font-mono text-gray-400">
          {row.timestamp.slice(11, 19)}
        </td>
        <td className="py-2 pr-2">
          <span className="rounded-full border border-gray-300 px-1.5 py-0.5 font-mono text-[10px] text-gray-600 dark:border-gray-700 dark:text-gray-400">
            {row.sender}
          </span>
          <span aria-hidden="true" className="mx-1 text-gray-400">
            →
          </span>
          <span className="rounded-full border border-gray-300 px-1.5 py-0.5 font-mono text-[10px] text-gray-600 dark:border-gray-700 dark:text-gray-400">
            {row.recipient}
          </span>
        </td>
        <td className="py-2 pr-2 font-mono text-[11px] text-gray-500">{row.stage}</td>
        <td className="py-2">
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            className="text-[11px] text-violet-700 underline dark:text-violet-300"
          >
            {open ? 'Hide work item' : 'Show work item'}
          </button>
        </td>
      </tr>
      {open && (
        <tr className="border-b border-gray-100 dark:border-gray-800">
          <td colSpan={5} className="pb-3">
            <pre className="max-h-64 overflow-auto rounded-lg border border-gray-200 bg-gray-50 p-2.5 font-mono text-[10.5px] leading-relaxed text-gray-600 dark:border-gray-800 dark:bg-gray-950 dark:text-gray-400">
              {JSON.stringify(row.work_item, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  )
}

/**
 * Render the toggleable chronological message log.
 *
 * @param props - The current run state.
 * @returns The log panel, or null before any messages have been reported.
 */
export function MessageLog({ state }: MessageLogProps) {
  const [shown, setShown] = useState(false)

  if (state.messages.length === 0 && state.sellerToSellerCount === null) {
    return null
  }

  const sellers = state.sellerOrder

  return (
    <section
      data-testid="message-log"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          Peer message log
        </h3>
        <span
          data-testid="opacity-check"
          className="rounded-full border border-emerald-500/50 px-2 py-0.5 font-mono text-[10px] text-emerald-700 dark:text-emerald-400"
        >
          ✓ opacity check: {state.sellerToSellerCount ?? 0} seller → seller messages
        </span>
        <button
          type="button"
          onClick={() => setShown((value) => !value)}
          aria-expanded={shown}
          className="ml-auto rounded-lg border border-gray-300 px-3 py-1.5 text-xs text-gray-700 hover:border-gray-400 dark:border-gray-700 dark:text-gray-300"
        >
          {shown ? 'Hide message log' : 'Show message log'}
        </button>
      </div>

      {shown && (
        <>
          {state.messages.length === 0 ? (
            <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
              No peer messages were exchanged.
            </p>
          ) : (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-200 text-left dark:border-gray-800">
                    <th className="py-2 pr-2 font-medium text-gray-500">#</th>
                    <th className="py-2 pr-2 font-medium text-gray-500">Time</th>
                    <th className="py-2 pr-2 font-medium text-gray-500">
                      Sender → recipient
                    </th>
                    <th className="py-2 pr-2 font-medium text-gray-500">Stage</th>
                    <th className="py-2 font-medium text-gray-500">Work item</th>
                  </tr>
                </thead>
                <tbody>
                  {state.messages.map((row) => (
                    <Row key={row.sequence} row={row} sellers={sellers} />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="mt-3 text-[11px] leading-relaxed text-gray-400 dark:text-gray-500">
            Every row names exactly one sender and one recipient. No row lists one
            supplier as sender and the other as recipient, because there is no channel
            between them to carry one — each agent&rsquo;s turn is assembled only from
            the messages addressed to it, so a supplier has nothing rival-specific to
            disclose even if it tries.
          </p>
        </>
      )}
    </section>
  )
}

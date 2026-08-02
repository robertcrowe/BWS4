// Built with Spec4 AI - https://spec4.ai
import { useState } from 'react'

import type { IdentityCard } from '../../api/collab'
import { useIdentityCards } from '../../api/useCollab'

/**
 * `collab_identity_cards`: what each peer publishes about itself.
 *
 * Two states per card, `collapsed` and `expanded`, per the surface spec. The
 * head is a real `<button>` with `aria-expanded` rather than a clickable
 * `<div>` — the mock draws a chevron and binds a click handler, which is a
 * control a keyboard cannot reach.
 *
 * The cards are fetched, never hardcoded here. They are the same constants the
 * negotiation is validated against server-side, so a local copy would be a
 * second source of truth free to drift from the one the run uses.
 *
 * What is deliberately *not* on a card: any private negotiating position. A
 * card is the public face; sealed constraints stay sealed until a run ends,
 * which is a later phase's surface.
 */

/** Copy shown while the cards are in flight. Static content renders above it regardless. */
const LOADING_MESSAGE = 'Loading the published identity cards…'

interface AgentPanelProps {
  agent: IdentityCard
}

function AgentPanel({ agent }: AgentPanelProps) {
  const [expanded, setExpanded] = useState(false)
  const { card } = agent
  const panelId = `agent-card-body-${agent.id}`

  return (
    <div
      data-testid={`agent-card-${agent.id}`}
      className="overflow-hidden rounded-xl border border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-gray-950"
    >
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => setExpanded((open) => !open)}
        className="flex w-full items-center gap-2 px-3.5 py-3 text-left hover:bg-gray-100 dark:hover:bg-gray-900"
      >
        <span
          aria-hidden="true"
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: agent.color }}
        />
        <strong className="text-[13.5px] font-semibold text-gray-900 dark:text-gray-100">
          {card.name}
        </strong>
        <span className="rounded-full border border-gray-300 px-2 py-0.5 font-mono text-[10px] uppercase text-gray-500 dark:border-gray-700 dark:text-gray-400">
          {agent.role}
        </span>
        <span
          aria-hidden="true"
          className={`ml-auto text-[10px] text-gray-400 transition-transform ${
            expanded ? 'rotate-90' : ''
          }`}
        >
          ▶
        </span>
      </button>

      {expanded && (
        <dl id={panelId} className="border-t border-gray-200 px-3.5 py-3 dark:border-gray-800">
          <dt className="font-mono text-[10px] uppercase tracking-wide text-gray-500">
            Description
          </dt>
          <dd className="mt-0.5 mb-2.5 text-[12.5px] leading-relaxed text-gray-600 dark:text-gray-400">
            {card.description}
          </dd>

          <dt className="font-mono text-[10px] uppercase tracking-wide text-gray-500">Provider</dt>
          <dd className="mt-0.5 mb-2.5 text-[12.5px] text-gray-600 dark:text-gray-400">
            {card.provider.organization}
          </dd>

          <dt className="font-mono text-[10px] uppercase tracking-wide text-gray-500">Skills</dt>
          <dd className="mt-0.5 mb-2.5 text-[12.5px] text-gray-600 dark:text-gray-400">
            <ul className="ml-4 list-disc space-y-0.5">
              {card.skills.map((skill) => (
                <li key={skill.id}>
                  <span className="text-gray-700 dark:text-gray-300">{skill.name}</span> —{' '}
                  {skill.description}
                </li>
              ))}
            </ul>
          </dd>

          <dt className="font-mono text-[10px] uppercase tracking-wide text-gray-500">
            Capabilities
          </dt>
          {/* A2A's capability flags are transport features, and every one is
              false here because there is no transport. Saying so is more use to
              a reader than three "false" rows. */}
          <dd className="mt-0.5 mb-2.5 text-[12.5px] text-gray-600 dark:text-gray-400">
            Streaming, push notifications and state-transition history are all declared{' '}
            <strong className="font-semibold text-gray-700 dark:text-gray-300">not supported</strong>{' '}
            — those are transport features, and this exchange has no network transport.
          </dd>

          <dt className="font-mono text-[10px] uppercase tracking-wide text-gray-500">
            Tool access
          </dt>
          <dd className="mt-0.5 mb-2.5 text-[12.5px] text-gray-600 dark:text-gray-400">
            <strong className="font-semibold text-gray-700 dark:text-gray-300">
              {card.toolAccess}
            </strong>{' '}
            — knowledge and messages only. This agent calls no tools and reaches no external
            service.
          </dd>

          <dt className="font-mono text-[10px] uppercase tracking-wide text-gray-500">
            Protocol version
          </dt>
          <dd className="mt-0.5 font-mono text-[12px] text-gray-600 dark:text-gray-400">
            A2A {card.protocolVersion} data model · no transport binding
          </dd>
        </dl>
      )}
    </div>
  )
}

/**
 * Render the three peer identity cards as inspectable panels.
 *
 * @returns The identity-cards panel.
 */
export function IdentityCards() {
  const query = useIdentityCards()

  return (
    <section
      data-testid="identity-cards"
      className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
    >
      <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
        Agent identity cards (inspectable before the run)
      </h3>

      {query.isPending && (
        <p className="mt-3 text-sm text-gray-500 dark:text-gray-400">{LOADING_MESSAGE}</p>
      )}

      {query.isError && (
        <p className="mt-3 text-sm text-red-600 dark:text-red-400">
          {query.error instanceof Error
            ? query.error.message
            : 'The identity cards could not be loaded.'}
        </p>
      )}

      {query.data && (
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          {query.data.agents.map((agent) => (
            <AgentPanel key={agent.id} agent={agent} />
          ))}
        </div>
      )}

      <p className="mt-3 text-xs leading-relaxed text-gray-400 dark:text-gray-500">
        Each card is what an A2A-style peer publishes about itself. Private constraints are{' '}
        <em>not</em> on the card — they stay sealed until the round ends.
      </p>
    </section>
  )
}

// Built with Spec4 AI - https://spec4.ai
import { useState } from 'react'

import { BuyerTrack } from './BuyerTrack'
import { DiffTable } from './DiffTable'
import { IdentityCards } from './IdentityCards'
import { MessageLog } from './message-log'
import { PatternOverview } from './PatternOverview'
import { RevealPanel } from './RevealPanel'
import { ScenarioForm } from './ScenarioForm'
import { SellerColumns } from './SellerColumns'
import { SensitivityPanel } from './SensitivityPanel'
import { StageRail } from './StageRail'
import { useCollabRun } from './useCollabRun'

/**
 * The multi-agent collaboration app.
 *
 * Surfaces in the advisory order the design gives them: overview, identity
 * cards, scenario form, then the run — stage rail, buyer track, parallel seller
 * columns, term-by-term diff, and the message log last, collapsed.
 *
 * **Results stay on screen.** Nothing here clears a completed run when a later
 * one is refused: the capability requires that a cap refusal leave previously
 * produced results visible, and `useCollabRun` only resets state when a new run
 * actually starts.
 *
 * The reveal sits below the diff table and the sensitivity projection below
 * that, matching the order the design gives them: what happened, then what each
 * party was carrying, then what a different weighting would likely have changed.
 * The message log stays last and collapsed — it is corroboration for a visitor
 * who wants it, not the first thing to read.
 *
 * @returns The collaboration app.
 */
export function CollabApp() {
  const [scenarioId, setScenarioId] = useState('')
  const [weightingId, setWeightingId] = useState('')
  const run = useCollabRun()

  return (
    <div className="space-y-5">
      <PatternOverview />
      <IdentityCards />

      <ScenarioForm
        scenarioId={scenarioId}
        weightingId={weightingId}
        onScenarioChange={setScenarioId}
        onWeightingChange={setWeightingId}
        onStart={() => run.start(scenarioId, weightingId)}
        pending={run.pending}
        state={run.state}
      />

      {run.state.phase !== 'idle' && (
        <section
          data-testid="negotiation-run"
          className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-800 dark:bg-gray-900"
        >
          <StageRail state={run.state} />
          {run.state.phase === 'connecting' && (
            <p data-testid="connecting" className="text-sm text-gray-500 dark:text-gray-400">
              Reserving the run&rsquo;s budget and composing the request for
              quotation… the backend sleeps when idle on its free tier, so the first
              response can take a few seconds.
            </p>
          )}
        </section>
      )}

      <BuyerTrack state={run.state} />
      <SellerColumns state={run.state} />
      <DiffTable state={run.state} />
      <RevealPanel state={run.state} />
      <SensitivityPanel state={run.state} />
      <MessageLog state={run.state} />
    </div>
  )
}

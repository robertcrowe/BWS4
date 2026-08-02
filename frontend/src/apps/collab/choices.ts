// Built with Spec4 AI - https://spec4.ai
/**
 * The two closed choice sets the scenario form offers.
 *
 * A pure module beside the components, the arrangement `plotTraces.ts` and
 * `format.ts` already use here: exporting a constant from a component file
 * puts it in React's fast-refresh path and produces an oxlint
 * `only-export-components` warning.
 *
 * ## Why these are duplicated from the backend, and why that is safe
 *
 * The ids mirror `backend/app/collab/scenarios.py`. They are duplicated rather
 * than fetched because the labels here are display copy the backend has no
 * endpoint for — and the duplication **fails safe**: every id is re-validated
 * server-side against the catalogue before anything is reserved, so a drift
 * produces a clean `unknown_scenario` refusal rather than a wrong run. The
 * same reasoning the RAG and tool-use example lists follow.
 */

/** One selectable scenario. */
export interface ScenarioChoice {
  id: string
  label: string
  detail: string
}

/** One selectable priority weighting. */
export interface WeightingChoice {
  id: string
  label: string
  description: string
}

/** The three procurement scenarios, in catalogue order. */
export const SCENARIOS: ScenarioChoice[] = [
  {
    id: 'refurbished_laptops_school',
    label: '240 refurbished laptops for a school district',
    detail: 'Needed before the autumn term — 30 days, 12-month warranty minimum.',
  },
  {
    id: 'lab_reagents_bulk',
    label: '500 litres of buffer solution for a research lab',
    detail: 'Within 21 days, with at least 12 months of shelf life on arrival.',
  },
  {
    id: 'fleet_tyres_replacement',
    label: '320 commercial van tyres for a delivery fleet',
    detail: 'Fitted within 14 days, with a tread-life warranty of two years or more.',
  },
]

/** The five priority weightings. */
export const WEIGHTINGS: WeightingChoice[] = [
  { id: 'lowest_price', label: 'Lowest price', description: 'Unit cost dominates.' },
  {
    id: 'fastest_delivery',
    label: 'Fastest delivery',
    description: 'Sooner matters more than cheaper.',
  },
  {
    id: 'full_quantity',
    label: 'Full quantity',
    description: 'A partial order is close to useless.',
  },
  {
    id: 'longest_warranty',
    label: 'Longest warranty',
    description: 'Cost of ownership over years.',
  },
  { id: 'balanced', label: 'Balanced', description: 'Best all-round offer wins.' },
]

# Built with Spec4 AI - https://spec4.ai
"""The ReAct loop example app: interleaved reason -> act -> observe.

The deliberate contrast with `backend/app/planning/`, which sits in the same
pattern tier: the planning agent decomposes a goal into a whole plan, shows it
for approval, and only then executes. Here nothing is planned. The model emits
one short thought, takes one action -- issue a search, or declare it can answer
-- reads the observation that action returned, and only then decides its next
step. Same tier, opposite commitment point.

Phase 1 lands the slice's scaffolding only: the preset catalogue, the request
and envelope schemas, and a model-free stub stream that proves the transport.
There is no loop here yet, and no call to a model or to Exa anywhere in this
package.
"""

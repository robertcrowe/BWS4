# Built with Spec4 AI - https://spec4.ai
"""The Router example app: one cheap classification call, then code dispatches.

Routing is not a tier in Spec4's pattern library and this package does not
claim one. The decision is tier 03 (single_call) -- exactly one model call
returning a typed object -- and everything after it is deterministic dispatch
to paths whose tiers are already cited: a no-model evaluator, a single call,
the RAG example's retriever, and web search plus one generation. The model that
decided never sees the result of the route it chose.

Phase 1 lands the slice's scaffolding only: the route-id constants and the
preset catalogue, served by a static endpoint. There is no classification call,
no evaluator and no dispatch here yet.
"""

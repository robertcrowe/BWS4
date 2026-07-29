# Built with Spec4 AI - https://spec4.ai
"""The embeddings_example_app package.

Layered the same way as backend/app/rag/: `schemas.py` holds the API
contract, `service.py` holds the domain logic (preset curation, the PCA
projection, and the in-process projection cache), and
`backend/app/api/embeddings.py` stays a thin handler over both.

Scaffolded in Phase 1; the preset embedding + PCA fit lands in Phase 2 and
custom-text placement in Phase 3.
"""

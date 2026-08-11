"""Narrative pass (M5, architecture §3.2): cartographer-generated module
docs, test-behavior one-liners, and inferred invariants, every claim
pinned ``file:line @ SHA``.

``schema`` defines and validates the artifacts (ADR-019), ``stale``
computes blob-level staleness, ``prompts``/``runner`` drive the headless
cartographer, and the orchestrator in this package ties them together
behind ``hobbes narrate`` (ADR-020).
"""

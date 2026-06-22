# Changelog

## [0.1.0] - 2026-06-22

### Added
- Initial flow-repair connector: `flow://host/repair/command/run` turns a
  natural-language goal into a urirun flow (YAML), validates every step URI
  against the registry action space, runs the steps under policy, and self-repairs
  from a failing step by feeding the structured error back to the LLM for a
  corrected flow (up to `tries`). LLM model/provider is delegated to the `llm`
  connector. Planner-injectable `repair_loop` for offline testing. CLI, manifest,
  pytest suite, entry point.

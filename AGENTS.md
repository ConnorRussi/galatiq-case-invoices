# Codex repository instructions

## Cdocs is a required part of implementation

For every meaningful repository change, update the relevant page in `Cdocs/` in the same change. This applies to code, tests, configuration, CLI behavior, data contracts, artifacts, workflows, policies, dependencies, and subsystem structure.

Before editing, read the applicable Cdocs area and its linked contract. After editing, make the documentation describe the resulting behavior—not the intended behavior—and keep it concise enough to route the next human or agent directly to the right code.

## Required update procedure

1. Identify the owning area: `ingestion`, `validation`, `approval`, `payment`, `acceptance`, or `orchestration`.
2. Update that area's `README.md` with any changed entry point, current-state label, input/output contract, ownership boundary, configuration, artifact, status/finding code, limit, or test coverage.
3. Update `Cdocs/system-map.md` whenever a module, runtime stage, or cross-area handoff changes.
4. Update `Cdocs/acceptance/README.md` when externally observable behavior, fixture coverage, or verification commands change.
5. Update `Cdocs/documentation-protocol.md` only when the documentation convention itself changes.

If a change establishes a durable new subsystem, create `Cdocs/<area>/README.md` using the template in `Cdocs/documentation-protocol.md` and add it to `Cdocs/README.md`.

## Completion rule

Do not mark a meaningful change complete until the corresponding Cdocs updates and proportionate tests are included. For a purely mechanical edit that does not alter any documented behavior, contract, ownership, operation, or acceptance evidence, do not create documentation churn; state in the final handoff that no Cdocs update was needed.

Never place secrets, API keys, sensitive source data, hidden reasoning, or transient run identifiers in Cdocs.

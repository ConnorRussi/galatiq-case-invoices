# Documentation protocol

## Purpose

Keep Cdocs a small, reliable routing layer for humans and agents. It should eliminate exploratory reading, not duplicate every function or preserve a changelog of incidental edits.

## Required with each behavior change

Update the owning Cdocs area in the same change when any of the following changes:

- public command, callable entry point, configuration key, environment variable, or default;
- input/output schema, status, issue code, side effect, artifact, or retry/limit behavior;
- module ownership, handoff to another stage, or an architectural decision;
- acceptance behavior, test fixture meaning, or evaluation expectation.

The update should name the current code path, say what is true after the change, and link to the relevant test or evaluator. Do not document secrets, tokens, raw sensitive source data, hidden reasoning, or transient run IDs.

## Change checklist

- [ ] Read the relevant Cdocs area before editing.
- [ ] Update its **Current state**, contract, and change-surface notes if affected.
- [ ] Add/adjust tests and record the meaningful acceptance coverage.
- [ ] Update `Cdocs/system-map.md` if a module, stage, or handoff changed.
- [ ] Create a new area folder if the work establishes a durable subsystem.
- [ ] Ensure links and commands still work from the repository root.

## New-area template

```markdown
# <Area>

**State:** implemented | partial | planned

## Purpose

## Current behavior

## Entry points and ownership

## Contracts

### Receives

### Produces

### Must not

## Change surface

## Tests and acceptance evidence

## Related documents
```

Use `planned` only for a deliberate contract/build queue. Flip it to `partial` or `implemented` with the first code change that makes the subsystem real.

## Status vocabulary

- **Implemented** — executable code owns the behavior and has proportionate verification.
- **Partial** — an executable slice exists but not the full intended contract.
- **Planned** — no executable behavior exists; this page defines the next bounded contract.
- **Deprecated** — code may still exist temporarily; the page tells contributors what replaces it.

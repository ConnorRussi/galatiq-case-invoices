# Maintaining the agent knowledge graph

This page describes how future coding agents should extend the docs.

## New domain page template

Create a descriptive page or folder under `docs/agents/<domain>/` with:

1. purpose and current status (`implemented`, `partial`, or `planned`);
2. source files and owning entry point;
3. input and output contracts;
4. graph edges to upstream and downstream stages;
5. tools, policies, limits, and failure behavior;
6. tests, fixtures, and acceptance checks;
7. safe extension points and known non-goals.

Link the page from [`docs/index.md`](index.md), [`docs/files.md`](files.md),
and the nearest architecture page.

## Change checklist

- Search the docs for every renamed symbol or file path.
- Update the graph when a node, route, state field, or ownership boundary moves.
- Update contracts when a serialized field, status, or artifact changes.
- Add a deterministic test before documenting a new guarantee.
- Label future work as planned; do not let the original case narrative imply
  that unimplemented stages are available.
- Keep generated output out of the graph; document its stable schema and location instead.


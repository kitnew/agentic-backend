# Custom Instructions

Always activate and route all code generation and modification through the installed
`ponytail` plugin ruleset. Follow the YAGNI ladder for every single line of code.

# Repository Guidance

Before making changes:

1. Read the nearest applicable `AGENTS.md`.
2. Read architecture/design documentation referenced by that `AGENTS.md`.
3. Inspect the current implementation before modifying it.
4. Distinguish target architecture from legacy/current implementation.

General rules:

- Prefer the smallest change that satisfies the requested behavior.
- Do not introduce new abstractions, compatibility layers, or migration machinery
  unless they are required by the task or documented architecture.
- Do not silently reinterpret documented architecture to fit the current code.
- If implementation and authoritative documentation conflict, report the conflict
  before making an architectural assumption.
- Preserve service boundaries and do not move domain responsibilities between
  services without explicit architectural justification.
- Keep transport, application, domain, and persistence concerns separated.
- Reuse shared contracts where they are the repository source of truth instead of
  duplicating request/response models.
- Run the relevant tests and validation commands for the area changed.
- Do not modify unrelated code while completing a scoped task.

# Architecture Documentation

Repository architecture and design documents live under `docs/`.

When a subsystem has dedicated architecture documentation, treat those documents
as the target design unless the user explicitly asks to revise that design.
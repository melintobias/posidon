# Domain Docs

How the engineering skills should consume this repo's domain documentation when
exploring the codebase.

## Before exploring, read these

- **`docs/GLOSSARY.md`**: the project glossary. Posidon keeps it under `docs/`,
  not at the repository root, because `AGENTS.md` keeps project documentation
  under `docs/`.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their
absence; don't suggest creating them upfront. The `/domain-modeling` skill
(reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates
them lazily when terms or decisions actually get resolved. When it does, create
the glossary at `docs/GLOSSARY.md`, never at the repository root.

## File structure

Posidon is a single-context repo: the `cli` and `core` workspace members share
one glossary and one set of ADRs.

```
/
├── docs/
│   ├── GLOSSARY.md
│   └── adr/
│       ├── 0001-<decision>.md
│       └── 0002-<decision>.md
├── cli/
└── core/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal,
a hypothesis, a test name), use the term as defined in `docs/GLOSSARY.md`. Don't
drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either
you're inventing language the project doesn't use (reconsider) or there's a real
gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than
silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_

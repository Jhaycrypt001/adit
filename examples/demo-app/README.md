# demo-app

A small TypeScript service used as the worked example in the project README.
It exists to make both halves of a reachability answer observable in one run,
on a real dependency with real advisories.

```
npm install --ignore-scripts
adit trace .
```

## What it is built to show

It depends on `lodash@4.17.20`, which OSV reports five advisories against. The
code reaches exactly one of the functions those advisories name:

| Route | Calls | Result |
|---|---|---|
| `handleOrder` → `scrubOrder` | `_.unset` | **reachable** — two advisories name `unset` |
| `handleOrder` → `normalizePayload` | `_.merge` | not reachable — no advisory on 4.17.20 covers `merge` |
| everything else | — | not reachable |

So a correct run reports **2 actionable, 3 not reachable**. A tool that flagged
all five would be a dependency scanner; a tool that flagged none would have
missed a real call path.

## The parts that are deliberately awkward

- `src/lib/index.ts` is a barrel that re-exports with `export *`. Nothing in it
  names `normalizePayload`, yet importers resolve it through there — the
  construct that defeats naive extractors.
- `src/orphan.ts` is never imported by anything, so it must stay out of every
  reachability answer.
- `src/services/order.ts` reaches lodash through a class method, so the call
  graph has to follow method dispatch rather than only free functions.

`lodash@4.17.20` is pinned exactly. Bumping it changes which advisories apply
and the numbers above stop matching.
